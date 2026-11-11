import { getJson, openBookingPage } from './booking-http.js';

const booking = document.querySelector('#booking');
const room = booking.dataset.room;
const today = booking.dataset.today;
const draftKey = 'lumenbook.booking.' + room;
const dates = booking.querySelector('.booking-dates');
const slots = booking.querySelector('.booking-slots');
const selection = booking.querySelector('.booking-selection');
const next = booking.querySelector('.booking-continue');
const form = booking.querySelector('.booking-form');
const retry = booking.querySelector('.booking-retry');
const error = booking.querySelector('.booking-error');
const formError = booking.querySelector('.booking-form-error');
const recovery = booking.querySelector('.booking-recovery');
const bookingId = booking.dataset.bookingId;
const duration = Number(booking.dataset.duration);
const bookingPath = '/my/bookings/' + bookingId;
const availabilityUrl = bookingId
  ? '/api/v1/bookings/' + bookingId + '/availability'
  : '/api/v1/rooms/' + room + '/availability';

const calendarDate = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'UTC', weekday: 'short', month: 'long', day: 'numeric',
});
const slotTime = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Europe/Moscow', hour: '2-digit', minute: '2-digit',
});
const currency = new Intl.NumberFormat('ru-RU', {
  style: 'currency', currency: 'RUB', minimumFractionDigits: 0, maximumFractionDigits: 2,
});

let day = today;
let availability;
let selected = [];
let requestNumber = 0;
let submitting = false;
let outcomeUnknown = false;

function message(element, value = '') {
  element.textContent = value;
  element.hidden = !value;
}

function button(label, action) {
  const element = document.createElement('button');
  element.type = 'button';
  element.textContent = label;
  element.addEventListener('click', action);
  return element;
}

function displayTime(startsAt, endsAt) {
  return slotTime.format(new Date(startsAt)) + '–' + slotTime.format(new Date(endsAt));
}

function displayDate(value) {
  return calendarDate.format(new Date(value + 'T00:00:00Z'));
}

function renderSummary() {
  const interval = selected.length
    ? displayTime(selected[0].starts_at, selected.at(-1).ends_at)
    : bookingId ? 'Выберите начало' : 'Выберите один или несколько часов';
  const total = bookingId
    ? currency.format(Number(booking.dataset.originalTotal) / 100)
    : selected.length ? currency.format(selected.length * availability.hourly_price_minor / 100) : '—';
  booking.querySelector('.booking-selected-time').textContent = interval;
  booking.querySelector('.booking-total').textContent = total;
  if (next) next.disabled = !selected.length || submitting || outcomeUnknown;
  if (form) {
    form.querySelector('.booking-form-summary').textContent =
      displayDate(day) + ' · ' + interval + ' МСК · ' + total;
  }
}

function paintSlots() {
  for (const [index, element] of [...slots.children].entries()) {
    element.setAttribute('aria-pressed', String(selected.includes(availability.slots[index])));
  }
  renderSummary();
}

function chooseSlot(slot) {
  if (submitting || outcomeUnknown) return;
  if (bookingId) {
    selected = rescheduleRange(availability.slots.indexOf(slot));
    form.hidden = true;
    message(error);
    paintSlots();
    return;
  }
  const position = selected.indexOf(slot);
  if (position >= 0) selected = position === 0 ? selected.slice(1) : selected.slice(0, position);
  else if (selected.at(-1)?.ends_at === slot.starts_at) selected.push(slot);
  else if (selected[0]?.starts_at === slot.ends_at) selected.unshift(slot);
  else selected = [slot];
  if (form) form.hidden = true;
  message(error);
  paintSlots();
}

function rescheduleRange(index) {
  const range = availability.slots.slice(index, index + duration);
  if (range.length !== duration || !range.every(slot => slot.available)) return [];
  if (Date.parse(range[0].starts_at) === Date.parse(booking.dataset.originalStart)) return [];
  return range;
}

function paintDates() {
  for (const element of dates.children) {
    element.setAttribute('aria-pressed', String(element.dataset.date === day));
  }
  booking.querySelector('.booking-date-label').textContent = displayDate(day);
}

function renderSlots() {
  const now = Date.parse(availability.server_now);
  slots.replaceChildren(...availability.slots.map((slot, index) => {
    const element = button(displayTime(slot.starts_at, slot.ends_at), () => chooseSlot(slot));
    const status = document.createElement('small');
    const fits = !bookingId || rescheduleRange(index).length > 0;
    status.textContent = slot.available
      ? (fits ? 'Свободно' : 'Недоступно для начала')
      : Date.parse(slot.starts_at) <= now ? 'Прошло' : 'Занято';
    element.dataset.state = slot.available ? 'free' : Date.parse(slot.starts_at) <= now ? 'past' : 'busy';
    element.append(status);
    element.disabled = !slot.available || !fits;
    return element;
  }));
  paintSlots();
}

async function loadDay(value, draft, feedback = '') {
  const request = ++requestNumber;
  day = value;
  availability = undefined;
  selected = [];
  slots.replaceChildren();
  slots.setAttribute('aria-busy', 'true');
  retry.hidden = true;
  if (form) form.hidden = true;
  paintDates();
  renderSummary();
  message(error, 'Загружаем время…');
  try {
    const result = await getJson(availabilityUrl + '?date=' + value);
    if (request !== requestNumber) return;
    availability = result;
    const hourlyPrice = document.querySelector('[data-hourly-price]');
    if (hourlyPrice) hourlyPrice.textContent = currency.format(result.hourly_price_minor / 100);
    if (draft) {
      const first = result.slots.findIndex(slot => slot.starts_at === draft.starts_at);
      const last = result.slots.findIndex(slot => slot.ends_at === draft.ends_at);
      const range = first >= 0 && last >= first ? result.slots.slice(first, last + 1) : [];
      if (range.length && range.every(slot => slot.available)) {
        selected = range;
        if (form) form.hidden = false;
        if (draft.room_version !== result.room_version) {
          feedback ||= 'Условия зала изменились. Проверьте сумму перед бронированием.';
        }
      } else {
        feedback ||= 'Выбранное время стало недоступно. Выберите другой интервал.';
      }
    }
    renderSlots();
    if (![...slots.children].some(element => !element.disabled)) {
      feedback ||= 'На эту дату нет подходящего времени.';
    }
    message(error, feedback);
  } catch (failure) {
    if (request !== requestNumber) return;
    if (bookingId && failure.status === 409) {
      openBookingPage(bookingPath, failure.message);
      return;
    }
    retry.hidden = false;
    message(error, failure.status ? failure.message : 'Не удалось загрузить время.');
  } finally {
    if (request === requestNumber) slots.removeAttribute('aria-busy');
  }
}

function currentDraft() {
  return {
    date: day, room_version: availability.room_version,
    starts_at: selected[0].starts_at, ends_at: selected.at(-1).ends_at,
  };
}

function goToLogin() {
  try {
    sessionStorage.setItem(draftKey, JSON.stringify(currentDraft()));
  } catch {
    message(error, 'Браузер не сохранил выбранное время. После входа выберите его снова.');
    return;
  }
  window.location.assign('/login?room=' + room);
}

retry.addEventListener('click', () => loadDay(day));
next?.addEventListener('click', () => {
  if (!selected.length) return;
  if (!form) {
    goToLogin();
    return;
  }
  message(formError);
  form.hidden = false;
  form.querySelector(bookingId ? 'h2' : 'input').focus();
});

form?.addEventListener('submit', async event => {
  event.preventDefault();
  if (submitting || outcomeUnknown || !selected.length) return;
  const draft = currentDraft();
  const fields = Object.fromEntries(new FormData(form));
  const interval = { starts_at: draft.starts_at, ends_at: draft.ends_at };
  const body = bookingId
    ? { ...interval, version: Number(booking.dataset.version) }
    : { ...fields, ...interval, room_id: room, room_version: draft.room_version };
  const submit = form.querySelector('.booking-submit');
  message(formError);
  submitting = true;
  submit.disabled = true;
  selection.disabled = true;
  renderSummary();
  let sent = false;
  try {
    const csrf = await getJson('/api/v1/auth/csrf');
    sent = true;
    const result = await getJson(bookingId ? '/api/v1/bookings/' + bookingId + '/reschedule' : '/api/v1/bookings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf.csrf_token },
      body: JSON.stringify(body),
    });
    if (bookingId) openBookingPage(bookingPath, result.message);
    else window.location.assign('/my/bookings/' + result.id);
  } catch (failure) {
    if (failure.status === 401) {
      if (bookingId) location.assign('/login');
      else goToLogin();
    } else if (failure.code === 'SLOT_UNAVAILABLE' || failure.code === 'INVALID_TIME_RANGE') {
      await loadDay(day, null, failure.message);
    } else if (failure.code === 'ROOM_SETTINGS_CHANGED') {
      await loadDay(day, draft, failure.message);
    } else if (bookingId && failure.status === 409) {
      openBookingPage(bookingPath, failure.message);
    } else if (sent && (!failure.status || failure.status >= 500)) {
      outcomeUnknown = true;
      message(formError, 'Не удалось получить результат. Проверьте актуальные данные брони.');
      recovery.hidden = false;
    } else {
      const field = failure.details?.find(item => form.elements.namedItem(item.field));
      message(formError, field?.message || (failure.status ? failure.message : 'Не удалось подключиться.'));
      if (field) form.elements.namedItem(field.field).focus();
    }
  } finally {
    submitting = false;
    submit.disabled = outcomeUnknown;
    selection.disabled = outcomeUnknown;
    renderSummary();
  }
});

const firstDate = new Date(today + 'T00:00:00Z');
const dateButtons = Array.from({ length: 31 }, (_, offset) => {
  const date = new Date(firstDate);
  date.setUTCDate(date.getUTCDate() + offset);
  const value = date.toISOString().slice(0, 10);
  const parts = calendarDate.formatToParts(date);
  const part = type => parts.find(item => item.type === type).value;
  const element = button(offset === 0 ? 'Сегодня' : part('weekday'), () => loadDay(value));
  const number = document.createElement('strong');
  number.textContent = date.getUTCDate();
  const month = document.createElement('small');
  month.textContent = part('month').slice(0, 3);
  element.append(number, month);
  element.dataset.date = value;
  element.setAttribute('aria-label', displayDate(value));
  return element;
});
dates.append(...dateButtons);

let draft;
if (!bookingId) {
  try {
    draft = JSON.parse(sessionStorage.getItem(draftKey) || 'null');
    sessionStorage.removeItem(draftKey);
  } catch {
    draft = null;
  }
}
const initialDay = bookingId ? booking.dataset.originalDay : draft?.date;
const restoredDay = dateButtons.find(element => element.dataset.date === initialDay);
if (restoredDay) {
  loadDay(initialDay, bookingId ? null : draft);
  dates.scrollLeft = restoredDay.offsetLeft - dates.firstElementChild.offsetLeft;
} else {
  loadDay(today, null, draft ? 'Сохранённая дата больше недоступна.' : '');
}
