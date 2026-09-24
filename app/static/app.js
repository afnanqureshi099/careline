document.querySelectorAll('[data-confirm]').forEach((form) => {
  form.addEventListener('submit', (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});

const browserAlertsButton = document.querySelector('#enable-browser-notifications');
if (browserAlertsButton && 'Notification' in window) {
  browserAlertsButton.addEventListener('click', async () => {
    const permission = await Notification.requestPermission();
    browserAlertsButton.textContent = permission === 'granted' ? 'Browser alerts enabled' : 'Browser alerts unavailable';
  });
}

if ('Notification' in window && Notification.permission === 'granted') {
  fetch('/api/notifications/unread')
    .then((response) => response.ok ? response.json() : [])
    .then((items) => items.forEach((item) => new Notification(item.title, { body: item.message })))
    .catch(() => {});
}
