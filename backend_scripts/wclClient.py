"""Async client for the Warcraft Logs v2 GraphQL API (client credentials).

Every request also selects rateLimitData, and the client sleeps until the hour resets once the pool
the request draws from is past POOL_SHARE: the overall pool, plus the "database" pool for rankings.
Report fetches never wait on the database pool, so a busy sweeper does not stall the worker.
"""
import asyncio
import os
import time

import aiohttp

API_URL = "https://www.warcraftlogs.com/api/v2/client"
TOKEN_URL = "https://www.warcraftlogs.com/oauth/token"
RATE_FIELDS = ("rateLimitData { limitPerHour pointsSpentThisHour databaseLimitPerHour "
               "databasePointsSpentThisHour pointsResetIn }")
POOL_SHARE = 0.85
RETRIES = 5
EVENTS_PAGE_LIMIT = 10000


class WclError(RuntimeError):
    """The API answered with GraphQL errors (private or archived report, bad query, ...)."""


class NoMplusZone(WclError):
    """WCL lists no single active Mythic+ zone (between seasons)."""


class WclClient:
    def __init__(self, session: aiohttp.ClientSession):
        self.session = session
        self.client_id = os.environ["WCL_CLIENT_ID"]
        self.client_secret = os.environ["WCL_CLIENT_SECRET"]
        self.token = None
        self.token_expires = 0
        self.rate = None

    async def _token(self):
        if self.token and time.time() < self.token_expires - 60:
            return self.token
        auth = aiohttp.encode_basic_auth(self.client_id, self.client_secret)
        async with self.session.post(TOKEN_URL, data={"grant_type": "client_credentials"},
                                     headers={"Authorization": auth}) as resp:
            resp.raise_for_status()
            body = await resp.json()
        self.token, self.token_expires = body["access_token"], time.time() + int(body["expires_in"])
        return self.token

    async def _pace(self, database):
        r = self.rate
        if not r:
            return
        if (r["pointsSpentThisHour"] >= POOL_SHARE * r["limitPerHour"]
                or database and r["databasePointsSpentThisHour"] >= POOL_SHARE * r["databaseLimitPerHour"]):
            wait = int(r["pointsResetIn"]) + 5
            print(f"[wcl] {r['pointsSpentThisHour']:.0f}/{r['limitPerHour']} points, "
                  f"{r['databasePointsSpentThisHour']:.0f}/{r['databaseLimitPerHour']} database points; "
                  f"sleeping {wait}s until the hour resets")
            await asyncio.sleep(wait)
            self.rate = None

    async def query(self, selection: str, variables: dict | None = None, var_defs: str = "", database=False):
        """Runs `query<var_defs> { <selection> rateLimitData {...} }` and returns its data. database:
        the query draws on the database points pool (rankings)."""
        body = {"query": f"query{var_defs} {{ {selection} {RATE_FIELDS} }}", "variables": variables or {}}
        attempt = 0
        while True:
            await self._pace(database)
            headers = {"Authorization": f"Bearer {await self._token()}"}
            try:
                async with self.session.post(API_URL, json=body, headers=headers) as resp:
                    if resp.status == 401 and attempt == 0:
                        self.token = None
                        raise aiohttp.ClientResponseError(resp.request_info, (), status=401)
                    if resp.status == 429:
                        await asyncio.sleep(float(resp.headers.get("Retry-After", 60)))
                        raise aiohttp.ClientResponseError(resp.request_info, (), status=429)
                    if 400 <= resp.status < 500:
                        raise WclError(f"HTTP {resp.status}: {(await resp.text())[:300]}")
                    resp.raise_for_status()
                    payload = await resp.json()
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                attempt += 1
                if attempt > RETRIES:
                    raise
                print(f"[wcl] {type(e).__name__} {getattr(e, 'status', '')}, retry {attempt}/{RETRIES}")
                await asyncio.sleep(2 ** attempt)
                continue
            if payload.get("errors"):
                raise WclError("; ".join(e.get("message", str(e)) for e in payload["errors"]))
            data = payload["data"]
            self.rate = data.pop("rateLimitData")
            return data

    async def mplus_zone(self):
        """The current Mythic+ zone: the non-frozen zone whose name contains "Mythic+"."""
        data = await self.query("worldData { zones { id name frozen encounters { id name } } }")
        zones = [z for z in data["worldData"]["zones"] if "Mythic+" in z["name"] and not z["frozen"]]
        if len(zones) != 1:
            raise NoMplusZone(f"Expected one active Mythic+ zone, found {[z['name'] for z in zones]}")
        return zones[0]

    async def character_rankings(self, encounter_id, class_name, spec_name, page, from_ms, to_ms):
        data = await self.query(
            "worldData { encounter(id: $id) { characterRankings(className: $cls, specName: $spec, "
            "page: $page, filter: $filter) } }",
            {"id": encounter_id, "cls": class_name, "spec": spec_name, "page": page,
             "filter": f"date.{from_ms}.{to_ms}"},
            "($id: Int!, $cls: String, $spec: String, $page: Int, $filter: String)", database=True)
        return data["worldData"]["encounter"]["characterRankings"]

    async def fight(self, code, fight_id):
        """The fight and the report's actors."""
        data = await self.query(
            "reportData { report(code: $code) { "
            "fights(fightIDs: [$fight]) { id name startTime endTime encounterID keystoneLevel keystoneTime "
            "friendlyPlayers friendlySpecs dungeonPulls { id encounterID startTime endTime } } "
            "masterData(translate: false) { actors { id gameID name type subType icon petOwner server } } } }",
            {"code": code, "fight": fight_id}, "($code: String!, $fight: Int!)")
        report = data["reportData"]["report"]
        if not report or not report["fights"]:
            raise WclError(f"Report {code} has no fight {fight_id}")
        return report["fights"][0], report["masterData"]["actors"]

    async def events(self, code, fight, queries: dict):
        """{alias: [event, ...]} for several `events` fields, each given as its extra arguments
        (e.g. 'dataType: Casts, hostilityType: Enemies'). They go out aliased in one request per
        round, which WCL bills as one query, and each pages on its own nextPageTimestamp."""
        out = {alias: [] for alias in queries}
        cursor = {alias: fight["startTime"] for alias in queries}
        while cursor:
            fields = " ".join(
                f"{alias}: events(fightIDs: [{fight['id']}], startTime: {start}, endTime: {fight['endTime']}, "
                f"limit: {EVENTS_PAGE_LIMIT}, {queries[alias]}) {{ data nextPageTimestamp }}"
                for alias, start in cursor.items())
            data = await self.query(f"reportData {{ report(code: $code) {{ {fields} }} }}",
                                    {"code": code}, "($code: String!)")
            report = data["reportData"]["report"]
            for alias in list(cursor):
                page = report[alias]
                out[alias].extend(page["data"])
                if page.get("nextPageTimestamp"):
                    cursor[alias] = page["nextPageTimestamp"]
                else:
                    del cursor[alias]
        return out
