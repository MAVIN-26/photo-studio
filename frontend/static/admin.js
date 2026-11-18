import { getJson, openBookingPage } from './booking-http.js';
import { initManualBooking } from './admin-create-booking.js';
import { initTimeBlocks } from './admin-blocks.js';

const grid = document.querySelector('.admin-grid');
const panel = document.querySelector('#booking-details');
const heading = panel.querySelector('h2');
const panelBody = panel.querySelector('.admin-drawer-body');
const notice = panel.querySelector('.admin-drawer-message');
const edit = panel.querySelector('.admin-reschedule');
const dateInput = edit.elements.day;
const startInput = edit.elements.start;
const submit = edit.querySelector('[type=submit]');
const retry = edit.querySelector('[data-retry]');
const availableInterval = edit.querySelector('[data-available-interval]');
const actionBar = panelBody.querySelector('.admin-drawer-actions');
const cancelDialog = document.querySelector('#booking-cancel');
const dateForm = document.querySelector('.admin-date-form');
const statuses = {
  pending_payment: 'Ожидает оплаты', paid: 'Оплачено',
  confirmed: 'Подтверждено', cancelled: 'Отменено',
};
const sources = {website: 'Сайт', phone: 'Звонок', telegram: 'Telegram', vk: 'VK'};
const timezone = {timeZone: 'Europe/Moscow'};
const isoDateFormat = new Intl.DateTimeFormat('en-CA', {
  ...timezone, year: 'numeric', month: '2-digit', day: '2-digit',
});
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

function localDate(value) {
  const parts = isoDateFormat.formatToParts(new Date(value));
  return ['year', 'month', 'day'].map(type => parts.find(part => part.type === type).value).join('-');
}

function timeRange(startsAt, endsAt) {
  return timeFormat.format(new Date(startsAt)) + '–' + timeFormat.format(new Date(endsAt));
}

function setNotice(message = '') {
  notice.textContent = message;
  notice.hidden = !message;
}

function pathFor(id, day) {
  return '/admin?' + new URLSearchParams({date: day, booking: id});
}

function apiPath(id) {
  return '/api/v1/admin/bookings/' + id;
}

function readNotice() {
  try {
    const key = 'lumenbook.booking-notice.' + location.pathname + location.search;
    const message = sessionStorage.getItem(key);
    sessionStorage.removeItem(key);
    return message || '';
  } catch {
    return '';
  }
}

let loading;
let slotRequest;
let current;
let saving = false;
let intervals = [];

async function openBooking(id, feedback = '') {
  loading?.abort();
  const request = new AbortController();
  loading = request;
  current = undefined;
  heading.textContent = 'Бронь ' + id.slice(0, 8);
  panelBody.hidden = true;
  edit.hidden = true;
  setNotice('Загрузка брони…');
  if (!panel.open) panel.showModal();
  try {
    const booking = await getJson(apiPath(id), {signal: request.signal});
    if (request.signal.aborted) return;
    const start = new Date(booking.starts_at);
    const end = new Date(booking.ends_at);
    const hours = (end - start) / 3600000;
    field('status', statuses[booking.status]).dataset.status = booking.status;
    field('contact_name', booking.contact_name);
    field('contact_phone', booking.contact_phone);
    field('room', booking.room_name);
    field('date', dayFormat.format(start));
    field('time', timeRange(start, end) + ' · ' + hours + ' ч');
    field('total', priceFormat.format(booking.total_price_minor / 100));
    field('created', createdFormat.format(new Date(booking.created_at)));
    field('source', sources[booking.source] ?? booking.source);
    field('comment', booking.comment).closest('section').hidden = !booking.comment;
    const eventTime = panelBody.querySelector('.admin-operation-time');
    const timestamp = booking.status === 'cancelled' ? booking.cancelled_at : booking.confirmed_at;
    const actionLabel = booking.status === 'cancelled' ? 'Отменена' : 'Подтверждена';
    eventTime.textContent = timestamp ? actionLabel + ' · ' + createdFormat.format(new Date(timestamp)) : '';
    eventTime.hidden = !timestamp;
    for (const button of actionBar.querySelectorAll('[data-action]')) {
      button.hidden = !booking.allowed_actions.includes(button.dataset.action);
    }
    actionBar.hidden = !booking.allowed_actions.length;
    for (const button of actionBar.querySelectorAll('button')) button.disabled = false;
    current = booking;
    setNotice(feedback);
    panelBody.hidden = false;
  } catch (error) {
    if (request.signal.aborted) return;
    if (error.status === 401) {
      location.assign('/login');
      return;
    }
    setNotice(error.status ? error.message : 'Не удалось загрузить бронь.');
  }
}

function intervalSummary(booking) {
  return booking.room_name + ' · ' + dayFormat.format(new Date(booking.starts_at)) +
    ' · ' + timeRange(booking.starts_at, booking.ends_at) + ' МСК';
}

function updateIntervalHint() {
  const interval = intervals[startInput.value];
  submit.disabled = !interval || saving;
  if (!interval) return;
  availableInterval.textContent = timeRange(interval.starts_at, interval.ends_at) + ' МСК · ' +
    priceFormat.format(current.total_price_minor / 100) + ' · сумма сохранится';
}

async function loadIntervals(feedback = '') {
  slotRequest?.abort();
  const request = new AbortController();
  slotRequest = request;
  intervals = [];
  startInput.replaceChildren();
  startInput.disabled = true;
  submit.disabled = true;
  retry.hidden = true;
  availableInterval.textContent = '';
  if (!dateInput.value || !dateInput.checkValidity()) return;
  availableInterval.textContent = 'Загрузка доступности…';
  setNotice(feedback);
  try {
    const result = await getJson(apiPath(current.id) + '/availability?date=' + dateInput.value,
      {signal: request.signal});
    if (request.signal.aborted) return;
    const hours = (Date.parse(current.ends_at) - Date.parse(current.starts_at)) / 3600000;
    for (const [index, slot] of result.slots.entries()) {
      const range = result.slots.slice(index, index + hours);
      if (range.length !== hours || range.some(item => !item.available)) continue;
      if (Date.parse(slot.starts_at) === Date.parse(current.starts_at)) continue;
      intervals.push({starts_at: slot.starts_at, ends_at: range.at(-1).ends_at});
    }
    if (!intervals.length) {
      availableInterval.textContent = 'На эту дату нет подходящего интервала.';
      return;
    }
    startInput.replaceChildren(...intervals.map((item, index) =>
      new Option(timeFormat.format(new Date(item.starts_at)), String(index))));
    startInput.disabled = false;
    updateIntervalHint();
  } catch (error) {
    if (request.signal.aborted) return;
    availableInterval.textContent = '';
    if (error.status === 401) location.assign('/login');
    else if (error.status === 409) {
      openBookingPage(pathFor(current.id, dateForm.elements.date.value), error.message);
    }
    else {
      setNotice(error.status ? error.message : 'Не удалось загрузить доступность.');
      retry.hidden = false;
    }
  }
}

function showReschedule() {
  const today = localDate(grid.dataset.now);
  const lastDay = new Date(today + 'T00:00:00Z');
  lastDay.setUTCDate(lastDay.getUTCDate() + 30);
  dateInput.min = today;
  dateInput.max = lastDay.toISOString().slice(0, 10);
  const original = localDate(current.starts_at);
  dateInput.value = original >= today && original <= dateInput.max ? original : today;
  edit.querySelector('[data-current-interval]').textContent = intervalSummary(current);
  const hours = (Date.parse(current.ends_at) - Date.parse(current.starts_at)) / 3600000;
  edit.querySelector('[data-duration]').textContent = 'Длительность · ' + hours + ' ч';
  panelBody.hidden = true;
  edit.hidden = false;
  dateInput.focus();
  loadIntervals();
}

async function changeBooking(action, interval = {}) {
  if (saving || !current) return;
  const booking = current;
  const previousDay = dateForm.elements.date.value;
  saving = true;
  dateInput.disabled = true;
  startInput.disabled = true;
  submit.disabled = true;
  for (const button of panel.querySelectorAll('button')) button.disabled = true;
  setNotice('Сохраняем изменения…');
  let sent = false;
  try {
    const csrf = await getJson('/api/v1/auth/csrf');
    sent = true;
    const result = await getJson(apiPath(booking.id) + '/' + action, {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf.csrf_token},
      body: JSON.stringify({version: booking.version, ...interval}),
    });
    const day = action === 'reschedule' ? localDate(result.starts_at) : previousDay;
    openBookingPage(pathFor(booking.id, day), result.message);
  } catch (error) {
    if (error.status === 401) location.assign('/login');
    else if (error.code === 'VERSION_CONFLICT' || error.code === 'INVALID_BOOKING_STATE') {
      openBookingPage(pathFor(booking.id, previousDay), error.message);
    } else if (sent && (!error.status || error.status >= 500)) {
      openBookingPage(pathFor(booking.id, previousDay), 'Проверьте актуальное состояние брони.');
    } else {
      saving = false;
      for (const button of panel.querySelectorAll('button')) button.disabled = false;
      dateInput.disabled = false;
      if (action === 'reschedule') loadIntervals(error.status ? error.message : 'Не удалось подключиться.');
      else setNotice(error.status ? error.message : 'Не удалось подключиться.');
    }
  }
}

actionBar.addEventListener('click', event => {
  const action = event.target.closest('[data-action]')?.dataset.action;
  if (saving || !current || !current.allowed_actions.includes(action)) return;
  if (action === 'confirm') changeBooking(action);
  else if (action === 'reschedule') showReschedule();
  else {
    cancelDialog.returnValue = '';
    cancelDialog.querySelector('[data-cancel-summary]').textContent =
      current.contact_name + ' · ' + intervalSummary(current);
    cancelDialog.showModal();
  }
});
cancelDialog.addEventListener('close', () => {
  if (cancelDialog.returnValue === 'confirm') changeBooking('cancel');
});
edit.addEventListener('submit', event => {
  event.preventDefault();
  const interval = intervals[startInput.value];
  if (interval) changeBooking('reschedule', interval);
});
dateInput.addEventListener('change', () => loadIntervals());
startInput.addEventListener('change', updateIntervalHint);
retry.addEventListener('click', () => loadIntervals());
edit.querySelector('[data-back]').addEventListener('click', () => {
  slotRequest?.abort();
  edit.hidden = true;
  panelBody.hidden = false;
  setNotice();
  actionBar.querySelector('[data-action="reschedule"]').focus();
});

grid?.addEventListener('click', event => {
  const button = event.target.closest('[data-booking-id]');
  if (button && !saving) openBooking(button.dataset.bookingId);
});
panel.addEventListener('close', () => {
  if (!panel.open) {
    loading?.abort();
    slotRequest?.abort();
    const url = new URL(location.href);
    if (url.searchParams.has('booking')) {
      url.searchParams.delete('booking');
      history.replaceState(null, '', url);
    }
  }
});
panel.addEventListener('cancel', event => {
  if (saving) event.preventDefault();
});
panel.addEventListener('click', event => {
  if (!saving && event.target === panel && event.clientX < panel.getBoundingClientRect().left) panel.close();
});

dateForm.elements.date.addEventListener('change', () => dateForm.requestSubmit());
const openedId = new URLSearchParams(location.search).get('booking');
if (openedId && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(openedId)) {
  openBooking(openedId, readNotice());
} else {
  const feedback = readNotice();
  const scheduleNotice = document.querySelector('.admin-schedule-notice');
  scheduleNotice.textContent = feedback;
  scheduleNotice.hidden = !feedback;
}

if (grid) {
  const marker = grid.querySelector('.admin-now');
  const initialTime = Date.parse(grid.dataset.now);
  const loadedAt = performance.now();
  function updateTime() {
    const now = new Date(initialTime + performance.now() - loadedAt);
    const date = localDate(now);
    const time = timeFormat.format(now);
    const [hours, minutes] = time.split(':').map(Number);
    for (const slot of grid.querySelectorAll('[data-hour]')) {
      slot.classList.toggle('is-past', grid.dataset.day < date
        || (grid.dataset.day === date && Number(slot.dataset.hour) <= hours));
      if (slot.matches('button')) slot.disabled = slot.classList.contains('is-past');
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

initManualBooking({grid, localDate, timeFormat, priceFormat, pathFor});
initTimeBlocks({grid, localDate, timeFormat, timeRange});
