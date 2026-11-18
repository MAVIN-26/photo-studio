import { getJson, openBookingPage } from './booking-http.js';

const booking = document.querySelector('#booking');
const room = booking.dataset.room;
const today = booking.dataset.today;
const draftKey = 'lumenbook.booking.' + room;
const confirmationKey = 'lumenbook.confirmation.' + location.pathname;
const confirmationHash = '#confirm-booking';
const dates = booking.querySelector('.booking-dates');
const slots = booking.querySelector('.booking-slots');
const selection = booking.querySelector('.booking-selection');
const next = booking.querySelector('.booking-continue');
const form = booking.querySelector('.booking-form');
const retry = booking.querySelector('.booking-retry');
const error = booking.querySelector('.booking-error');
const formError = booking.querySelector('.booking-form-error');
const recovery = booking.querySelector('.booking-recovery');
const conflict = booking.querySelector('#booking-conflict');
const selectionContent = [...document.querySelectorAll('[data-selection-content]')];
const bookingId = booking.dataset.bookingId;
const duration = Number(booking.dataset.duration);
const bookingPath = '/my/bookings/' + bookingId;
const availabilityUrl = bookingId
  ? '/api/v1/bookings/' + bookingId + '/availability'
  : '/api/v1/rooms/' + room + '/availability';

const calendarDate = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'UTC', weekday: 'short', month: 'long', day: 'numeric',
});
const shortCalendarDate = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'UTC', month: 'long', day: 'numeric',
});
const slotTime = new Intl.DateTimeFormat('ru-RU', {
  timeZone: 'Europe/Moscow', hour: '2-digit', minute: '2-digit',
});
const currency = new Intl.NumberFormat('ru-RU', {
  style: 'currency', currency: 'RUB', minimumFractionDigits: 0, maximumFractionDigits: 2,
});
const hourNumber = new Intl.NumberFormat('ru-RU', {style: 'unit', unit: 'hour', unitDisplay: 'long'});

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

function setStep(confirming, focus = true) {
  for (const element of selectionContent) element.hidden = confirming;
  if (form) form.hidden = !confirming;
  if (!focus) return;
  const target = confirming ? form.querySelector('h1') : next;
  if (target?.disabled) booking.scrollIntoView();
  else target?.focus();
}

function openConfirmation() {
  if (!form || !selected.length) return;
  try {
    sessionStorage.setItem(confirmationKey, JSON.stringify(currentDraft()));
  } catch {
    // Подтверждение работает в текущей вкладке и без сохранения черновика.
  }
  if (location.hash !== confirmationHash) {
    history.pushState({bookingConfirmation: true}, '', confirmationHash);
  }
  setStep(true);
}

function returnToSelection() {
  if (location.hash === confirmationHash) history.replaceState(null, '', '#booking');
  setStep(false);
}

function renderSummary() {
  const interval = selected.length
    ? displayTime(selected[0].starts_at, selected.at(-1).ends_at)
    : bookingId ? 'Выберите начало' : 'Выберите один или несколько часов';
  const total = bookingId
    ? currency.format(Number(booking.dataset.originalTotal) / 100)
    : selected.length ? currency.format(selected.length * availability.hourly_price_minor / 100) : '—';
  booking.querySelector('.booking-selected-time').textContent =
    selected.length ? displayDate(day) + ' · ' + interval : interval;
  booking.querySelector('[data-selected-duration]').textContent =
    selected.length ? hourNumber.format(selected.length) : '';
  booking.querySelector('.booking-total').textContent = total;
  if (next) next.disabled = !selected.length || submitting || outcomeUnknown;
  if (form && selected.length) {
    if (bookingId) {
      form.querySelector('[data-review-summary]').textContent = displayDate(day) + ' · ' + interval + ' МСК';
    } else {
      const rate = currency.format(availability.hourly_price_minor / 100);
      form.querySelector('[data-review-rate]').textContent = rate + ' за час';
      form.querySelector('[data-review-date]').textContent = displayDate(day);
      form.querySelector('[data-review-time]').textContent = interval + ' МСК';
      form.querySelector('[data-review-duration]').textContent = hourNumber.format(selected.length);
      form.querySelector('[data-review-total]').textContent = total;
      form.querySelector('[data-review-calculation]').textContent = rate + ' × ' + selected.length;
    }
  }
}

function paintSlots() {
  for (const [index, element] of [...slots.children].entries()) {
    const chosen = selected.includes(availability.slots[index]);
    element.setAttribute('aria-pressed', String(chosen));
    if (element.dataset.state === 'free') {
      element.querySelector('small').textContent = chosen ? 'Выбрано' : 'Свободно';
    }
  }
  renderSummary();
}

function chooseSlot(slot) {
  if (submitting || outcomeUnknown) return;
  if (bookingId) {
    selected = rescheduleRange(availability.slots.indexOf(slot));
    message(error);
    paintSlots();
    return;
  }
  const position = selected.indexOf(slot);
  if (position >= 0) selected = position === 0 ? selected.slice(1) : selected.slice(0, position);
  else if (selected.at(-1)?.ends_at === slot.starts_at) selected.push(slot);
  else if (selected[0]?.starts_at === slot.ends_at) selected.unshift(slot);
  else selected = [slot];
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
  const lastDay = dateButtons.at(-1).dataset.date;
  booking.querySelector('[data-booking-horizon]').textContent = day === lastDay
    ? 'Даты после ' + shortCalendarDate.format(new Date(lastDay + 'T00:00:00Z')) + ' пока недоступны.'
    : 'Бронировать можно на 30 дней вперёд · до ' + displayDate(lastDay) + '.';
}

function renderSlots() {
  const now = Date.parse(availability.server_now);
  const blocked = new Set((availability.blocked_starts ?? []).map(value => Date.parse(value)));
  slots.replaceChildren(...availability.slots.map((slot, index) => {
    const element = button(displayTime(slot.starts_at, slot.ends_at), () => chooseSlot(slot));
    const status = document.createElement('small');
    const fits = !bookingId || rescheduleRange(index).length > 0;
    const start = Date.parse(slot.starts_at);
    const state = start <= now ? 'past'
      : blocked.has(start) ? 'blocked' : !slot.available ? 'busy' : fits ? 'free' : 'no-start';
    const labels = {past: 'Прошло', blocked: 'Недоступно', busy: 'Занято', free: 'Свободно',
      'no-start': 'Недоступно для начала'};
    status.textContent = labels[state];
    element.dataset.state = state;
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
  setStep(false, false);
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
        if (draft.room_version !== result.room_version) {
          feedback ||= 'Условия зала изменились. Проверьте сумму перед бронированием.';
        }
      } else {
        feedback ||= 'Выбранное время стало недоступно. Выберите другой интервал.';
      }
    }
    renderSlots();
    if (form && draft && selected.length) {
      openConfirmation();
      message(formError, feedback);
    } else if (location.hash === confirmationHash) {
      returnToSelection();
    }
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
    if (location.hash === confirmationHash) returnToSelection();
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
  openConfirmation();
});

form?.querySelector('[data-change-time]').addEventListener('click', () => {
  if (submitting || outcomeUnknown) return;
  if (history.state?.bookingConfirmation) history.back();
  else returnToSelection();
});
window.addEventListener('hashchange', () => {
  if (submitting || conflict?.open) return;
  setStep(Boolean(form && selected.length && location.hash === confirmationHash));
});

let conflictMessage = '';
conflict?.addEventListener('close', async () => {
  returnToSelection();
  await loadDay(day, null, conflictMessage);
  dates.querySelector('[aria-pressed="true"]')?.focus();
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
  form.querySelector('[data-change-time]').disabled = true;
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
    try {
      sessionStorage.removeItem(confirmationKey);
    } catch {
      // Запись уже сохранена на сервере.
    }
    const destination = bookingId ? '/my/bookings?tab=upcoming' : '/my/bookings/' + result.id;
    openBookingPage(destination, result.message + (bookingId
      ? ' «' + booking.dataset.roomName + '» · ' + displayDate(day) + ' · ' +
        displayTime(draft.starts_at, draft.ends_at) + ' МСК.' : ''));
  } catch (failure) {
    if (failure.status === 401) {
      if (bookingId) location.assign('/login');
      else goToLogin();
    } else if (failure.code === 'SLOT_UNAVAILABLE' && conflict) {
      conflictMessage = failure.message;
      conflict.querySelector('[data-conflict-interval]').textContent = '«' + booking.dataset.roomName +
        '» · ' + displayDate(day) + ' · ' + displayTime(draft.starts_at, draft.ends_at);
      conflict.showModal();
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
    form.querySelector('[data-change-time]').disabled = outcomeUnknown;
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
try {
  if (location.hash === confirmationHash) {
    draft = JSON.parse(sessionStorage.getItem(confirmationKey) || 'null');
  } else if (!bookingId) {
    draft = JSON.parse(sessionStorage.getItem(draftKey) || 'null');
    sessionStorage.removeItem(draftKey);
  }
} catch {
  draft = null;
}
const initialDay = draft?.date ?? (bookingId ? booking.dataset.originalDay : undefined);
const restoredDay = dateButtons.find(element => element.dataset.date === initialDay);
if (restoredDay) {
  loadDay(initialDay, draft);
  dates.scrollLeft = restoredDay.offsetLeft - dates.firstElementChild.offsetLeft;
} else {
  loadDay(today, null, draft ? 'Сохранённая дата больше недоступна.' : '');
}
