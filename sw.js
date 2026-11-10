// Service worker do viveiro: recebe os avisos do servidor (Web Push) e mostra a notificação no aparelho.
// Tocar na notificação abre o sistema (ou traz para a frente a aba que já estiver aberta).
// Não guarda páginas em cache: o sistema sempre abre a versão mais nova.

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (evento) => evento.waitUntil(self.clients.claim()));

const daqui = (caminho) => new URL(caminho, self.registration.scope).href;

self.addEventListener("push", (evento) => {
  let aviso = {};
  try {
    aviso = evento.data ? evento.data.json() : {};
  } catch {
    aviso = { texto: evento.data ? evento.data.text() : "" };
  }
  evento.waitUntil(self.registration.showNotification(aviso.titulo || "Viveiro Tabuões", {
    body: aviso.texto || "",
    tag: aviso.tag,               // o aviso novo do mesmo tipo substitui o anterior na bandeja
    renotify: Boolean(aviso.tag), // ... mas ainda assim toca e vibra
    icon: daqui("icone-192.png"),
    badge: daqui("icone-selo.png"),
    lang: "pt-BR",
    data: { url: daqui(aviso.url || "./") },
  }));
});

self.addEventListener("notificationclick", (evento) => {
  evento.notification.close();
  const destino = evento.notification.data?.url || self.registration.scope;
  evento.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((abertas) => {
    const aba = abertas.find((c) => c.url.startsWith(self.registration.scope));
    return aba ? aba.focus() : self.clients.openWindow(destino);
  }));
});
