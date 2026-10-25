/* Service worker (NFA-02, A24): shows pushes and opens the app on a tap. No caching:
   the app needs the server anyway. Served from /sw.js so its scope is the whole app. */

self.addEventListener("push", (event) => {
  let data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = { body: event.data ? event.data.text() : "" };
  }
  event.waitUntil(
    self.registration.showNotification(data.title || "", {
      body: data.body || "",
      tag: data.tag,
      icon: "/static/icons/icon-192.png",
      data: { url: data.url || "/" },
    }),
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  // Only paths inside the app; anything else opens the start page.
  let url = new URL(event.notification.data?.url || "/", self.location.origin);
  if (url.origin !== self.location.origin) url = new URL("/", self.location.origin);
  event.waitUntil(
    self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((windows) => {
      const same = windows.find((w) => w.url === url.href);
      if (same) return same.focus();
      const any = windows.find((w) => "navigate" in w);
      if (any) return any.navigate(url.href).then((w) => (w ? w.focus() : undefined));
      return self.clients.openWindow(url.href);
    }),
  );
});
