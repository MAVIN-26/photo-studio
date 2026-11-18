import { getJson } from './booking-http.js';

const grid = document.querySelector('.admin-grid');
const panel = document.querySelector('#booking-details');
const heading = panel.querySelector('h2');
const panelBody = panel.querySelector('.admin-drawer-body');
const notice = panel.querySelector('.admin-drawer-message');
const statuses = {
  pending_payment: 'Ожидает оплаты', paid: 'Оплачено',
  confirmed: 'Подтверждено', cancelled: 'Отменено',
};
const sources = {website: 'Сайт', phone: 'Звонок', telegram: 'Telegram', vk: 'VK'};
const timezone = {timeZone: 'Europe/Moscow'};
const timeFormat = new Intl.DateTimeFormat('ru-RU', {
  ...timezone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});
const dayFormat = new Intl.DateTimeFormat('ru-RU', {
  ...timezone, weekday: 'short', day: 'numeric', month: 'long',
});
const createdFormat = new Intl.DateTimeFormat('ru-RU', {
  ...timezone, day: 'numeric', month: 'long', year: 'numeric',
  hour: '2-digit', minute: '2-digit',
});
const priceFormat = new Intl.NumberFormat('ru-RU', {
  style: 'currency', currency: 'RUB', minimumFractionDigits: 0, maximumFractionDigits: 2,
});

function field(name, value) {
  const element = panelBody.querySelector('[data-field="' + name + '"]');
  element.textContent = value;
  return element;
}

let loading;
async function openBooking(button) {
  loading?.abort();
  const request = new AbortController();
  loading = request;
  const id = button.dataset.bookingId;
  heading.textContent = 'Бронь ' + id.slice(0, 8);
  panelBody.hidden = true;
  notice.hidden = false;
  notice.textContent = 'Загрузка брони…';
  if (!panel.open) panel.showModal();
  try {
    const booking = await getJson('/api/v1/admin/bookings/' + id, {signal: request.signal});
    if (request.signal.aborted) return;
    const start = new Date(booking.starts_at);
    const end = new Date(booking.ends_at);
    const hours = (end - start) / 3600000;
    field('status', statuses[booking.status]).dataset.status = booking.status;
    field('contact_name', booking.contact_name);
    field('contact_phone', booking.contact_phone);
    field('room', button.closest('.admin-room').querySelector('.admin-column-heading strong').textContent);
    field('date', dayFormat.format(start));
    field('time', timeFormat.format(start) + '–' + timeFormat.format(end) + ' · ' + hours + ' ч');
    field('total', priceFormat.format(booking.total_price_minor / 100));
    field('created', createdFormat.format(new Date(booking.created_at)));
    field('source', sources[booking.source] ?? booking.source);
    field('comment', booking.comment).closest('section').hidden = !booking.comment;
    notice.hidden = true;
    panelBody.hidden = false;
  } catch (error) {
    if (request.signal.aborted) return;
    if (error.status === 401) {
      location.assign('/login');
      return;
    }
    notice.textContent = error.status ? error.message : 'Не удалось загрузить бронь.';
  }
}

grid?.addEventListener('click', event => {
  const button = event.target.closest('[data-booking-id]');
  if (button) openBooking(button);
});
panel.addEventListener('close', () => {
  if (!panel.open) loading?.abort();
});
panel.addEventListener('click', event => {
  if (event.target === panel && event.clientX < panel.getBoundingClientRect().left) panel.close();
});

const dateForm = document.querySelector('.admin-date-form');
dateForm.elements.date.addEventListener('change', () => dateForm.requestSubmit());

if (grid) {
  const marker = grid.querySelector('.admin-now');
  const initialTime = Date.parse(grid.dataset.now);
  const loadedAt = performance.now();
  const dateFormat = new Intl.DateTimeFormat('en-CA', {
    ...timezone, year: 'numeric', month: '2-digit', day: '2-digit',
  });
  function updateTime() {
    const now = new Date(initialTime + performance.now() - loadedAt);
    const parts = dateFormat.formatToParts(now);
    const date = ['year', 'month', 'day'].map(type => parts.find(part => part.type === type).value).join('-');
    const time = timeFormat.format(now);
    const [hours, minutes] = time.split(':').map(Number);
    for (const slot of grid.querySelectorAll('[data-hour]')) {
      slot.classList.toggle('is-past', grid.dataset.day < date
        || (grid.dataset.day === date && Number(slot.dataset.hour) <= hours));
    }
    if (marker) {
      marker.hidden = date !== grid.dataset.day || hours < 9 || hours >= 23;
      marker.style.setProperty('--elapsed-hours', String(hours - 9 + minutes / 60));
      marker.querySelector('time').textContent = time;
    }
  }
  updateTime();
  setInterval(updateTime, 30000);
}
