/**
 * Injects dismissible site notifications from assets/json/notifications.json
 * (written by pageGeneration.load_notifications) into #page-notifications, skipping
 * ones the visitor already dismissed. They are never in the static HTML, so a
 * dismissed banner cannot flash and crawlers do not index them.
 *
 * Dismissals persist per browser in localStorage under a key identical on every
 * page, so dismissing on one page hides it everywhere. Like the theme preference
 * this is first-party functional storage, so it is not gated behind Klaro.
 */
(function () {
    "use strict";

    var STORAGE_KEY = "mythistone.dismissedNotifications";

    function readDismissed() {
        try {
            var raw = window.localStorage.getItem(STORAGE_KEY);
            if (!raw) {
                return [];
            }
            var parsed = JSON.parse(raw);
            return Array.isArray(parsed) ? parsed : [];
        } catch (e) {
            return [];
        }
    }

    function recordDismissed(key) {
        try {
            var list = readDismissed();
            if (list.indexOf(key) === -1) {
                list.push(key);
                window.localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
            }
        } catch (e) {
            /* private mode / storage disabled: nothing to persist, degrade quietly */
        }
    }

    function el(tag, className) {
        var node = document.createElement(tag);
        if (className) {
            node.className = className;
        }
        return node;
    }

    function buildAlert(n) {
        var wrap = el("div", "container-fluid");
        var alert = el("div", "alert alert-" + (n.type || "warning") +
            " alert-dismissible d-flex align-items-center mx-3 my-2 page-notification");
        alert.setAttribute("role", "alert");
        alert.setAttribute("data-notification-key", n.key);

        var icon = el("span", "material-symbols-rounded me-2");
        icon.setAttribute("aria-hidden", "true");
        icon.textContent = "announcement";
        alert.appendChild(icon);

        var body = el("div", "flex-fill");
        body.innerHTML = n.message; // trusted repo data, rendered with | safe before
        alert.appendChild(body);

        if (n.link && n.link_text) {
            var link = el("a", "btn btn-sm btn-light ms-3");
            link.href = n.link;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.textContent = n.link_text;
            alert.appendChild(link);
        }

        var close = el("button", "btn-close ms-3");
        close.type = "button";
        close.setAttribute("data-bs-dismiss", "alert");
        close.setAttribute("aria-label", "Close");
        var closeIcon = el("span", "material-symbols-rounded me-2");
        closeIcon.setAttribute("aria-hidden", "true");
        closeIcon.textContent = "close";
        close.appendChild(closeIcon);
        alert.appendChild(close);

        wrap.appendChild(alert);
        return wrap;
    }

    var slot = document.getElementById("page-notifications");
    if (!slot) {
        return;
    }
    var page = slot.getAttribute("data-page");
    var dungeon = slot.getAttribute("data-dungeon");

    fetch("/assets/json/notifications.json", { cache: "no-cache" })
        .then(function (res) {
            if (!res.ok) {
                throw new Error("HTTP " + res.status);
            }
            return res.json();
        })
        .then(function (notifications) {
            var dismissed = readDismissed();
            notifications.forEach(function (n) {
                // Same filter as the Jinja condition in templates/notifications.html.
                var onPage = !n.page || n.page === page || (dungeon && n.page === dungeon);
                if (n.message && onPage && dismissed.indexOf(n.key) === -1) {
                    slot.appendChild(buildAlert(n));
                }
            });
        })
        .catch(function (err) {
            console.error("Failed to load notifications:", err);
        });

    // Bootstrap fires close.bs.alert (bubbling) before it removes the element, and its
    // data-bs-dismiss handler is delegated on document, so injected alerts need no wiring.
    document.addEventListener("close.bs.alert", function (e) {
        var target = e.target;
        if (!target || !target.classList || !target.classList.contains("page-notification")) {
            return;
        }
        var key = target.getAttribute("data-notification-key");
        if (key) {
            recordDismissed(key);
        }
    });
})();
