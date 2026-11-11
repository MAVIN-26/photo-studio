import { getJson, openBookingPage } from './booking-http.js';

const pagePath = location.pathname + location.search;
const notice = document.querySelector('[data-booking-notice]');
try {
  const key = 'lumenbook.booking-notice.' + pagePath;
  const text = sessionStorage.getItem(key);
  sessionStorage.removeItem(key);
  if (text) {
    notice.textContent = text;
    notice.hidden = false;
  }
} catch {
  // Статус брони доступен на странице.
}

for (const actions of document.querySelectorAll('[data-booking-id][data-version]')) {
  const pay = actions.querySelector('[data-pay]');
  const cancel = actions.querySelector('[data-cancel]');
  const dialog = actions.querySelector('dialog');
  const error = actions.querySelector('[role=alert]');
  const buttons = [pay, cancel].filter(Boolean);
  let busy = false;

  async function submit(action) {
    if (busy) return;
    busy = true;
    buttons.forEach(element => { element.disabled = true; });
    error.hidden = true;
    let sent = false;
    try {
      const csrf = await getJson('/api/v1/auth/csrf');
      sent = true;
      const result = await getJson('/api/v1/bookings/' + actions.dataset.bookingId + '/' + action, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf.csrf_token },
        body: JSON.stringify({version: Number(actions.dataset.version)}),
      });
      openBookingPage(pagePath, result.message);
    } catch (failure) {
      if (failure.status === 401) {
        location.assign('/login');
      } else if (failure.status === 409) {
        openBookingPage(pagePath, failure.message);
      } else if (sent && (!failure.status || failure.status >= 500)) {
        openBookingPage(pagePath, 'Проверьте актуальный статус брони.');
      } else {
        error.textContent = failure.status ? failure.message : 'Не удалось подключиться. Повторите попытку.';
        error.hidden = false;
        busy = false;
        buttons.forEach(element => { element.disabled = false; });
      }
    }
  }

  pay?.addEventListener('click', () => submit('pay'));
  cancel?.addEventListener('click', () => {
    dialog.returnValue = '';
    dialog.showModal();
  });
  dialog?.addEventListener('close', () => {
    if (dialog.returnValue === 'confirm') submit('cancel');
  });
}
