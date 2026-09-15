// 404 page canvas animation (moved out of the 404Page.html inline <script>).
// Self-contained, no page data or shared-helper dependencies.
        (function () {
          // Canvas initialization and particle loop to ensure full-coverage and proper DPI scaling
          const canvas = document.getElementById('ms404-canvas');
          if (!canvas) return;
          const ctx = canvas.getContext('2d');
          let DPR = window.devicePixelRatio || 1;

          function resizeCanvas() {
            // Set CSS width/height remain, but ensure backing buffer matches DPR
            const cssW = canvas.offsetWidth || canvas.clientWidth || window.innerWidth;
            const cssH = canvas.offsetHeight || canvas.clientHeight || window.innerHeight;
            canvas.width = Math.max(1, Math.round(cssW * DPR));
            canvas.height = Math.max(1, Math.round(cssH * DPR));
            // scale so drawing operations use CSS pixels
            ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
          }

          // Simple drifting particles
          let particles = [];
          function createParticles() {
            const w = canvas.offsetWidth || window.innerWidth;
            const h = canvas.offsetHeight || window.innerHeight;
            const count = Math.max(30, Math.floor((w * h) / 48000));
            particles = [];
            for (let i = 0; i < count; i++) {
              particles.push({
                x: Math.random() * w,
                y: Math.random() * h,
                vx: (Math.random() - 0.5) * 0.14,
                vy: - (0.05 + Math.random() * 0.4),
                r: 0.6 + Math.random() * 2.6,
                a: 0.02 + Math.random() * 0.36,
                tw: 0.006 + Math.random() * 0.02
              });
            }
          }

          // draw loop
          let last = performance.now();
          function draw(now) {
            const dt = Math.min(50, now - last) / 16.666;
            last = now;
            const w = canvas.offsetWidth || window.innerWidth;
            const h = canvas.offsetHeight || window.innerHeight;

            // clear + subtle gradient
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            const grad = ctx.createLinearGradient(0, 0, 0, h);
            grad.addColorStop(0, 'rgba(255,255,255,0.01)');
            grad.addColorStop(1, 'rgba(0,0,0,0.12)');
            ctx.fillStyle = grad;
            ctx.fillRect(0, 0, w, h);

            // particles
            for (let p of particles) {
              p.x += p.vx * dt * 12;
              p.y += p.vy * dt * 12;
              p.a += Math.sin(now * p.tw) * 0.004;
              if (p.y < -10) { p.y = h + 10; p.x = Math.random() * w; }
              if (p.x < -20) p.x = w + 20;
              if (p.x > w + 20) p.x = -20;
              ctx.beginPath();
              ctx.globalAlpha = Math.max(0, Math.min(1, p.a));
              ctx.fillStyle = 'rgba(170,140,255,0.95)';
              ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
              ctx.fill();
              ctx.globalAlpha = 1;
            }

            requestAnimationFrame(draw);
          }

          // on resize, recreate backing buffer and particles
          function handleResize() {
            DPR = window.devicePixelRatio || 1;
            resizeCanvas();
            createParticles();
          }

          window.addEventListener('resize', () => {
            clearTimeout(window.__ms404_resize);
            window.__ms404_resize = setTimeout(handleResize, 96);
          });

          // initial setup
          handleResize();
          requestAnimationFrame(draw);

        })();
