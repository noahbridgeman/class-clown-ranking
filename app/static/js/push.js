/* Push on this device (NOT-01, A24). Registers the service worker on every page, so the
   app can be installed (NFA-02). Elements with data-push get a data-state:
   off | on | denied | unsupported | ios | missing | failed. The browser asks for
   permission only when "Push aktivieren" is clicked. */

(() => {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  const boxes = [...document.querySelectorAll("[data-push]")];
  const logoutFields = [...document.querySelectorAll("[data-push-endpoint]")];
  const csrf = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const supported =
    "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
  const standalone =
    window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  const ios =
    /iP(hone|ad|od)/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

  const setState = (state) => boxes.forEach((box) => (box.dataset.state = state));

  const post = (url, body) =>
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify(body),
    }).then((response) => {
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    });

  const subscription = async () => {
    if (!supported) return null;
    const registration = await navigator.serviceWorker.ready;
    return registration.pushManager.getSubscription();
  };

  const serverKey = (base64url) => {
    const base64 = (base64url + "=".repeat((4 - (base64url.length % 4)) % 4))
      .replace(/-/g, "+")
      .replace(/_/g, "/");
    return Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  };

  const currentState = async () => {
    if (!supported) return ios && !standalone ? "ios" : "unsupported";
    if (!boxes[0]?.dataset.key) return "missing";
    if (Notification.permission === "denied") return "denied";
    const sub = await subscription();
    if (!sub) return "off";
    // On only if the server has it for this account; another account's subscription on
    // this device is taken over by a click, never silently (NOT-01).
    const response = await fetch(boxes[0].dataset.status, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrf },
      body: JSON.stringify({ endpoint: sub.endpoint }),
    });
    return response.ok && (await response.json()).subscribed ? "on" : "off";
  };

  const enable = async (box) => {
    try {
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setState(permission === "denied" ? "denied" : "off");
        return;
      }
      const registration = await navigator.serviceWorker.ready;
      const sub =
        (await registration.pushManager.getSubscription()) ||
        (await registration.pushManager.subscribe({
          userVisibleOnly: true,
          applicationServerKey: serverKey(box.dataset.key),
        }));
      await post(box.dataset.subscribe, sub.toJSON());
      setState("on");
    } catch {
      setState("failed");
    }
  };

  const disable = async (box) => {
    try {
      const sub = await subscription();
      if (sub) {
        await post(box.dataset.unsubscribe, { endpoint: sub.endpoint });
        await sub.unsubscribe();
      }
      setState("off");
    } catch {
      setState("failed");
    }
  };

  boxes.forEach((box) => {
    box.querySelector("[data-push-enable]")?.addEventListener("click", () => enable(box));
    box.querySelector("[data-push-disable]")?.addEventListener("click", () => disable(box));
  });

  if (boxes.length) {
    currentState()
      .then(setState)
      .catch(() => setState("failed"));
  }

  // Logging out ends this device's pushes: the server forgets the subscription and the
  // browser drops it, so the next account has to switch push on itself (NOT-01).
  logoutFields.forEach((field) => {
    const form = field.form;
    let ready = false;
    form.addEventListener("submit", async (event) => {
      if (ready) return;
      event.preventDefault();
      try {
        const sub = await subscription();
        if (sub) {
          field.value = sub.endpoint;
          await sub.unsubscribe();
        }
      } catch {
        // Logging out must work even if the browser refuses.
      }
      ready = true;
      form.requestSubmit ? form.requestSubmit() : form.submit();
    });
  });
})();
