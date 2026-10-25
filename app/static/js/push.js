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
    return (await subscription()) ? "on" : "off";
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
    currentState().then(async (state) => {
      setState(state);
      // The server may have dropped it, or another account used this device before.
      if (state === "on") {
        const sub = await subscription();
        post(boxes[0].dataset.subscribe, sub.toJSON()).catch(() => {});
      }
    });
  }

  // Logging out ends this device's pushes for the account.
  logoutFields.forEach((field) => {
    subscription()
      .then((sub) => {
        if (sub) field.value = sub.endpoint;
      })
      .catch(() => {});
  });
})();
