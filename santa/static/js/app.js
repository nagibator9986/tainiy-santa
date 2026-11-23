/* Тайный Санта: снег, звёзды, отсчёт, конверт, мелкие удобства. */
(function () {
  "use strict";

  var reduceMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  var csrf = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
    } catch (e) { /* приватный режим — живём без памяти */ }
    return null;
  }

  function plural(n, one, few, many) {
    n = Math.abs(n) % 100;
    if (n > 10 && n < 20) return many;
    n %= 10;
    if (n === 1) return one;
    if (n >= 2 && n <= 4) return few;
    return many;
  }

  /* ------------------------------------------------------------ снег */
  var snow = (function () {
    var canvas = document.getElementById("snow");
    if (!canvas || !canvas.getContext) return null;
    var ctx = canvas.getContext("2d");
    var flakes = [], W = 0, H = 0, raf = 0, t = 0, running = false;

    var sprite = document.createElement("canvas");
    sprite.width = sprite.height = 64;
    (function () {
      var s = sprite.getContext("2d");
      var g = s.createRadialGradient(32, 32, 0, 32, 32, 32);
      g.addColorStop(0, "rgba(255,255,255,1)");
      g.addColorStop(0.35, "rgba(255,255,255,.85)");
      g.addColorStop(1, "rgba(255,255,255,0)");
      s.fillStyle = g;
      s.fillRect(0, 0, 64, 64);
    })();

    function make(anywhere) {
      var depth = Math.random();
      var bokeh = Math.random() < 0.025;
      return {
        x: Math.random() * W,
        y: anywhere ? Math.random() * H : -20,
        r: bokeh ? 5 + Math.random() * 5 : 0.7 + depth * 2.6,
        vy: bokeh ? 1.1 + Math.random() * 0.6 : 0.3 + depth * 1.05,
        phase: Math.random() * Math.PI * 2,
        sway: 0.3 + Math.random() * 1.2,
        a: bokeh ? 0.22 : 0.35 + depth * 0.6
      };
    }

    function resize() {
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = window.innerWidth;
      H = window.innerHeight;
      canvas.width = Math.round(W * dpr);
      canvas.height = Math.round(H * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      var target = Math.min(240, Math.round((W * H) / 7200));
      if (reduceMotion) target = Math.round(target / 3);
      while (flakes.length < target) flakes.push(make(true));
      flakes.length = target;
      if (!running) draw(0);
    }

    function draw(step) {
      t += 0.01 * step;
      var wind = Math.sin(t * 0.7) * 0.55 + Math.sin(t * 0.23 + 1) * 0.45;
      ctx.clearRect(0, 0, W, H);
      for (var i = 0; i < flakes.length; i++) {
        var f = flakes[i];
        if (step) {
          f.y += f.vy * step;
          f.x += (wind * f.vy * 0.7 + Math.sin(t * 2 + f.phase) * 0.35 * f.sway) * step;
          if (f.y > H + 20) flakes[i] = f = make(false);
          if (f.x > W + 20) f.x = -20;
          else if (f.x < -20) f.x = W + 20;
        }
        var size = f.r * 4;
        ctx.globalAlpha = f.a;
        ctx.drawImage(sprite, f.x - size / 2, f.y - size / 2, size, size);
      }
      ctx.globalAlpha = 1;
    }

    var last = 0;
    function frame(now) {
      var step = last ? Math.min((now - last) / 16.67, 3) : 1;
      last = now;
      draw(step);
      raf = window.requestAnimationFrame(frame);
    }

    function start() {
      if (running || reduceMotion) return;
      running = true;
      last = 0;
      canvas.hidden = false;
      raf = window.requestAnimationFrame(frame);
    }

    function stop(hide) {
      running = false;
      window.cancelAnimationFrame(raf);
      if (hide) canvas.hidden = true;
    }

    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", function () {
      if (document.hidden) stop(false);
      else if (store("snow") !== "off") start();
    });
    resize();
    return { start: start, stop: stop };
  })();

  var toggle = document.querySelector("[data-snow-toggle]");
  function setSnow(on) {
    if (toggle) toggle.setAttribute("aria-pressed", on ? "true" : "false");
    if (!snow) return;
    if (on) { document.getElementById("snow").hidden = false; snow.start(); }
    else snow.stop(true);
  }
  setSnow(store("snow") !== "off");
  if (toggle) {
    toggle.addEventListener("click", function () {
      var on = toggle.getAttribute("aria-pressed") !== "true";
      store("snow", on ? "on" : "off");
      setSnow(on);
    });
  }

  /* ------------------------------------------------------------ звёзды */
  document.querySelectorAll(".sky[data-stars]").forEach(function (sky) {
    var n = parseInt(sky.getAttribute("data-stars"), 10) || 60;
    var frag = document.createDocumentFragment();
    for (var i = 0; i < n; i++) {
      var s = document.createElement("span");
      var big = Math.random() < 0.08;
      s.className = big ? "star star--big" : "star";
      s.style.left = (Math.random() * 100).toFixed(2) + "%";
      s.style.top = (Math.pow(Math.random(), 1.4) * 82).toFixed(2) + "%";
      s.style.setProperty("--s", (big ? 2.6 : 1 + Math.random() * 1.4).toFixed(1) + "px");
      s.style.setProperty("--t", (2.5 + Math.random() * 4).toFixed(2) + "s");
      s.style.setProperty("--d", (-Math.random() * 6).toFixed(2) + "s");
      frag.appendChild(s);
    }
    sky.appendChild(frag);
  });

  /* ------------------------------------------------------------ отсчёт */
  document.querySelectorAll("[data-countdown]").forEach(function (el) {
    var target = parseInt(el.getAttribute("data-countdown"), 10);
    if (!target) return;
    var timer;
    function pad(n) { return n < 10 ? "0" + n : "" + n; }
    function tick() {
      var s = Math.floor((target - Date.now()) / 1000);
      if (s <= 0) {
        el.textContent = el.getAttribute("data-done") || "";
        window.clearInterval(timer);
        return;
      }
      var d = Math.floor(s / 86400); s %= 86400;
      var h = Math.floor(s / 3600); s %= 3600;
      var m = Math.floor(s / 60); s %= 60;
      el.innerHTML =
        "<span>до вручения</span>" +
        (d ? "<span><b>" + d + "</b>" + plural(d, "день", "дня", "дней") + "</span>" : "") +
        "<span><b>" + pad(h) + "</b>ч</span>" +
        "<span><b>" + pad(m) + "</b>мин</span>" +
        "<span><b>" + pad(s) + "</b>с</span>";
    }
    tick();
    timer = window.setInterval(tick, 1000);
  });

  /* ------------------------------------------------------------ конверт */
  var envelope = document.querySelector(".envelope[data-open-url]");
  if (envelope) {
    var opened = false;
    var openEnvelope = function () {
      if (opened) return;
      opened = true;
      envelope.removeAttribute("role");
      envelope.removeAttribute("tabindex");
      envelope.classList.add("is-opening");
      fetch(envelope.getAttribute("data-open-url"), {
        method: "POST",
        headers: { "X-CSRF-Token": csrf },
        credentials: "same-origin"
      }).catch(function () {});

      var sparks = envelope.querySelector(".env-sparks");
      var colors = ["#f0d38c", "#ffffff", "#ff8a7a", "#ffd36b"];
      for (var i = 0; i < 22 && !reduceMotion; i++) {
        var sp = document.createElement("span");
        var angle = Math.random() * Math.PI * 2;
        var dist = 50 + Math.random() * 90;
        sp.className = "spark";
        sp.style.setProperty("--dx", (Math.cos(angle) * dist).toFixed(1) + "px");
        sp.style.setProperty("--dy", (Math.sin(angle) * dist - 20).toFixed(1) + "px");
        sp.style.setProperty("--c", colors[i % colors.length]);
        sp.style.animationDelay = (Math.random() * 0.15).toFixed(2) + "s";
        sparks.appendChild(sp);
      }

      window.setTimeout(function () {
        envelope.classList.add("is-open");
        document.querySelectorAll("[data-sealed-hint]").forEach(function (h) { h.hidden = true; });
        var giftee = document.getElementById("giftee");
        if (giftee) {
          giftee.hidden = false;
          giftee.classList.add("reveal");
          window.setTimeout(function () {
            giftee.scrollIntoView({ behavior: reduceMotion ? "auto" : "smooth", block: "start" });
          }, 900);
        }
        if (sparks) window.setTimeout(function () { sparks.innerHTML = ""; }, 1200);
      }, reduceMotion ? 50 : 2150);
    };
    envelope.addEventListener("click", openEnvelope);
    envelope.addEventListener("keydown", function (e) {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openEnvelope(); }
    });
  }

  /* ------------------------------------------------------------ копирование */
  function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise(function (resolve, reject) {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try { document.execCommand("copy") ? resolve() : reject(); } catch (e) { reject(e); }
      document.body.removeChild(ta);
    });
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-copy]");
    if (!btn) return;
    var label = btn.querySelector("span") || btn;
    var original = label.getAttribute("data-label") || label.textContent;
    label.setAttribute("data-label", original);
    copyText(btn.getAttribute("data-copy")).then(function () {
      btn.classList.add("is-done");
      label.textContent = btn.getAttribute("data-copied") || "Скопировано";
    }, function () {
      window.prompt("Скопируйте вручную:", btn.getAttribute("data-copy"));
    });
    window.setTimeout(function () {
      btn.classList.remove("is-done");
      label.textContent = original;
    }, 2200);
  });

  /* ------------------------------------------------------------ подтверждения */
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (e) {
      if (!window.confirm(form.getAttribute("data-confirm"))) e.preventDefault();
    });
  });

  /* меню строки: открыто только одно, закрывается по клику мимо */
  document.addEventListener("toggle", function (e) {
    var d = e.target;
    if (!d.classList || !d.classList.contains("row-menu") || !d.open) return;
    document.querySelectorAll(".row-menu[open]").forEach(function (other) {
      if (other !== d) other.open = false;
    });
  }, true);
  document.addEventListener("click", function (e) {
    if (e.target.closest(".row-menu")) return;
    document.querySelectorAll(".row-menu[open]").forEach(function (d) { d.open = false; });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    document.querySelectorAll(".row-menu[open]").forEach(function (d) { d.open = false; });
  });

  /* ------------------------------------------------------------ жеребьёвка */
  var drawForm = document.querySelector("form[data-draw]");
  var overlay = document.querySelector("[data-draw-overlay]");
  if (drawForm && overlay) {
    drawForm.addEventListener("submit", function (e) {
      if (drawForm.dataset.sending) return;
      e.preventDefault();
      drawForm.dataset.sending = "1";
      overlay.hidden = false;
      window.setTimeout(function () { drawForm.submit(); }, reduceMotion ? 100 : 2300);
    });
  }

  /* ------------------------------------------------------------ письмо: несохранённые правки */
  document.querySelectorAll("form[data-dirty-guard]").forEach(function (form) {
    var label = form.querySelector("[data-dirty-label]");
    var initial = new FormData(form);
    var dirty = false;
    form.addEventListener("input", function () {
      dirty = false;
      new FormData(form).forEach(function (value, key) {
        if (initial.get(key) !== value) dirty = true;
      });
      if (label) {
        if (!label.hasAttribute("data-clean")) label.setAttribute("data-clean", label.textContent.trim());
        label.textContent = dirty ? label.getAttribute("data-dirty-text") : label.getAttribute("data-clean");
        label.classList.toggle("is-dirty", dirty);
      }
    });
    form.addEventListener("submit", function () { dirty = false; });
    window.addEventListener("beforeunload", function (e) {
      if (dirty) { e.preventDefault(); e.returnValue = ""; }
    });
  });

  /* PIN — только цифры */
  document.querySelectorAll(".pin-input").forEach(function (input) {
    input.addEventListener("input", function () {
      var clean = input.value.replace(/\D+/g, "").slice(0, 6);
      if (clean !== input.value) input.value = clean;
    });
  });

  /* ------------------------------------------------------------ уведомления */
  function dismiss(toast) {
    if (!toast || toast.classList.contains("is-leaving")) return;
    toast.classList.add("is-leaving");
    window.setTimeout(function () { toast.remove(); }, 350);
  }
  document.querySelectorAll(".toast").forEach(function (toast, i) {
    var close = toast.querySelector("[data-toast-close]");
    if (close) close.addEventListener("click", function () { dismiss(toast); });
    if (!toast.classList.contains("toast--error")) {
      window.setTimeout(function () { dismiss(toast); }, 6500 + i * 900);
    }
  });
})();
