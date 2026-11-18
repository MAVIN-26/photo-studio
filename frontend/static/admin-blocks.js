import { getJson, openBookingPage } from './booking-http.js';

const reasons = {cleaning: 'Уборка', repair: 'Ремонт'};

function message(element, text = '') {
  element.textContent = text;
  element.hidden = !text;
}

async function post(url, body) {
  const csrf = await getJson('/api/v1/auth/csrf');
  return getJson(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf.csrf_token},
    body: JSON.stringify(body),
  });
}

export function initTimeBlocks({grid, localDate, timeFormat, timeRange}) {
  const createDialog = document.querySelector('#admin-block-create');
  if (!createDialog) return;
  initCreate({createDialog, grid, localDate, timeFormat, timeRange});
  initRemoval({grid, localDate, timeRange});
}

function initCreate({createDialog, grid, localDate, timeFormat, timeRange}) {
  const trigger = document.querySelector('[data-new-block]');
  const form = createDialog.querySelector('form');
  const {room, day, start, end} = form.elements;
  const submit = form.querySelector('[type=submit]');
  const retry = form.querySelector('[data-retry]');
  const error = form.querySelector('[role=alert]');
  const availability = form.querySelector('[data-availability]');
  let snapshot;
  let request;
  let saving = false;

  function timestamp(hour) {
    return day.value + 'T' + hour + ':00+03:00';
  }

  function setConflict(text = '') {
    message(error, text);
    for (const field of [start, end]) {
      if (text) field.setAttribute('aria-invalid', 'true');
      else field.removeAttribute('aria-invalid');
    }
  }

  function validate(feedback = '') {
    submit.disabled = true;
    setConflict();
    if (saving || !snapshot || !start.value || !end.value) {
      message(error, feedback);
      return;
    }
    if (start.value >= end.value) {
      setConflict('Время начала должно быть раньше времени окончания.');
      return;
    }
    const startsAt = Date.parse(timestamp(start.value));
    const endsAt = Date.parse(timestamp(end.value));
    if (startsAt <= Date.parse(snapshot.server_now)) {
      setConflict('Этот час уже начался. Выберите другое время.');
      return;
    }
    const booking = snapshot.bookings.find(entry =>
      Date.parse(entry.starts_at) < endsAt && Date.parse(entry.ends_at) > startsAt);
    const block = snapshot.blocks.find(entry =>
      Date.parse(entry.starts_at) < endsAt && Date.parse(entry.ends_at) > startsAt);
    if (booking) {
      setConflict('На это время есть бронь: ' + booking.contact_name + ', ' +
        timeRange(booking.starts_at, booking.ends_at) +
        '. Перенесите или отмените её, чтобы закрыть время.');
    } else if (block) {
      setConflict('Время уже закрыто: ' + reasons[block.reason] + ', ' +
        timeRange(block.starts_at, block.ends_at) + '. Выберите другой интервал.');
    } else {
      message(error, feedback);
      submit.disabled = false;
    }
  }

  function hourLabel(hour) {
    return String(hour).padStart(2, '0') + ':00';
  }

  async function loadSchedule(previous = {}, feedback = '') {
    request?.abort();
    const active = new AbortController();
    request = active;
    snapshot = undefined;
    start.replaceChildren();
    end.replaceChildren();
    start.disabled = end.disabled = true;
    retry.hidden = true;
    message(availability);
    validate(feedback);
    if (!day.value || !day.checkValidity()) return;
    message(availability, 'Загрузка расписания…');
    try {
      const query = new URLSearchParams({date_from: day.value, date_to: day.value, room_id: room.value});
      const result = await getJson('/api/v1/admin/schedule?' + query, {signal: active.signal});
      if (active.signal.aborted) return;
      snapshot = result;
      const selectedRoom = result.rooms[0];
      const opens = Number(selectedRoom.opens_at.slice(0, 2));
      const closes = Number(selectedRoom.closes_at.slice(0, 2));
      const now = Date.parse(result.server_now);
      const occupied = [...result.bookings, ...result.blocks];
      let firstFree;
      for (let hour = opens; hour < closes; hour += 1) {
        const label = hourLabel(hour);
        const at = Date.parse(timestamp(label));
        if (at <= now && previous.start !== label) continue;
        const busy = occupied.some(entry => Date.parse(entry.starts_at) <= at && Date.parse(entry.ends_at) > at);
        start.add(new Option(label + (busy ? ' · занято' : ''), label));
        if (!busy && at > now && firstFree === undefined) firstFree = hour;
      }
      for (let hour = opens + 1; hour <= closes; hour += 1) {
        const label = hourLabel(hour);
        end.add(new Option(label, label));
      }
      start.value = [...start.options].some(option => option.value === previous.start)
        ? previous.start : firstFree === undefined ? '' : hourLabel(firstFree);
      end.value = [...end.options].some(option => option.value === previous.end)
        ? previous.end : start.value ? timeFormat.format(new Date(Date.parse(timestamp(start.value)) + 3600000)) : '';
      start.disabled = !start.options.length;
      end.disabled = !start.options.length;
      message(availability, firstFree === undefined ? 'На выбранную дату нет свободных часов.' : '');
      validate(feedback);
    } catch (failure) {
      if (active.signal.aborted) return;
      if (failure.status === 401) {
        location.assign('/login');
        return;
      }
      message(availability);
      message(error, failure.status ? failure.message : 'Не удалось загрузить расписание.');
      retry.hidden = false;
    }
  }

  function lock(locked) {
    saving = locked;
    for (const control of createDialog.querySelectorAll('input, select, button')) control.disabled = locked;
  }

  trigger.disabled = false;
  trigger.addEventListener('click', () => {
    form.reset();
    day.value = grid.dataset.day >= day.min && grid.dataset.day <= day.max ? grid.dataset.day : day.min;
    createDialog.showModal();
    loadSchedule();
  });
  for (const button of createDialog.querySelectorAll('[data-close]')) {
    button.addEventListener('click', () => createDialog.close());
  }
  createDialog.addEventListener('cancel', event => { if (saving) event.preventDefault(); });
  createDialog.addEventListener('close', () => request?.abort());
  room.addEventListener('change', () => loadSchedule());
  day.addEventListener('change', () => loadSchedule());
  start.addEventListener('change', () => {
    if (start.value && (!end.value || end.value <= start.value)) {
      end.value = timeFormat.format(new Date(Date.parse(timestamp(start.value)) + 3600000));
    }
    validate();
  });
  end.addEventListener('change', () => validate());
  retry.addEventListener('click', () => loadSchedule());
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (saving || submit.disabled) return;
    const previous = {start: start.value, end: end.value};
    const payload = {
      room_id: room.value, reason: form.elements.reason.value,
      starts_at: timestamp(previous.start), ends_at: timestamp(previous.end),
    };
    lock(true);
    try {
      const block = await post('/api/v1/admin/blocks', payload);
      const roomName = snapshot.rooms[0].name;
      const result = 'Время закрыто: «' + roomName + '», ' +
        timeRange(block.starts_at, block.ends_at) + ' · ' + reasons[block.reason];
      openBookingPage('/admin?date=' + localDate(block.starts_at), result);
    } catch (failure) {
      if (failure.status === 401) location.assign('/login');
      else if (!failure.status || failure.status >= 500) {
        openBookingPage('/admin?date=' + day.value, 'Проверьте актуальное расписание.');
      } else {
        lock(false);
        if (['SLOT_UNAVAILABLE', 'INVALID_TIME_RANGE'].includes(failure.code)) {
          loadSchedule(previous, failure.message);
        } else {
          validate(failure.message);
        }
      }
    }
  });
}

function initRemoval({grid, localDate, timeRange}) {
  const dialog = document.querySelector('#admin-block-detail');
  const state = dialog.querySelector('[data-block-state]');
  const fields = dialog.querySelector('dl');
  const error = dialog.querySelector('[role=alert]');
  const remove = dialog.querySelector('[data-remove-block]');
  const confirmation = dialog.querySelector('[data-confirm-removal]');
  const confirm = dialog.querySelector('[data-confirm-remove]');
  const keep = dialog.querySelector('[data-keep-block]');
  let request;
  let block;
  let saving = false;

  async function open(trigger) {
    request?.abort();
    const active = new AbortController();
    request = active;
    const id = trigger.dataset.blockId;
    block = undefined;
    remove.hidden = true;
    confirmation.hidden = true;
    fields.hidden = true;
    message(error);
    message(state, 'Загрузка блокировки…');
    dialog.showModal();
    try {
      const result = await getJson('/api/v1/admin/blocks/' + id, {signal: active.signal});
      if (active.signal.aborted) return;
      block = result;
      const roomHeading = trigger.closest('.admin-room').querySelector('.admin-column-heading strong');
      fields.querySelector('[data-block-room]').textContent = roomHeading.textContent;
      fields.querySelector('[data-block-day]').textContent = localDate(block.starts_at);
      fields.querySelector('[data-block-interval]').textContent = timeRange(block.starts_at, block.ends_at) + ' МСК';
      fields.querySelector('[data-block-reason]').textContent = reasons[block.reason];
      fields.hidden = false;
      message(state, block.status === 'active' ? 'Время закрыто' : 'Блокировка снята');
      remove.hidden = block.status !== 'active';
    } catch (failure) {
      if (active.signal.aborted) return;
      if (failure.status === 401) location.assign('/login');
      else {
        message(state);
        message(error, failure.status ? failure.message : 'Не удалось загрузить блокировку.');
      }
    }
  }

  grid.addEventListener('click', event => {
    const trigger = event.target.closest('[data-block-id]');
    if (trigger) open(trigger);
  });
  remove.addEventListener('click', () => {
    remove.hidden = true;
    confirmation.hidden = false;
    keep.focus();
  });
  keep.addEventListener('click', () => {
    confirmation.hidden = true;
    remove.hidden = false;
    remove.focus();
  });
  dialog.addEventListener('close', () => request?.abort());
  dialog.addEventListener('cancel', event => { if (saving) event.preventDefault(); });
  confirm.addEventListener('click', async () => {
    if (!block || saving) return;
    saving = true;
    const buttons = [...dialog.querySelectorAll('button')];
    for (const button of buttons) button.disabled = true;
    message(error);
    const path = '/admin?date=' + grid.dataset.day;
    try {
      await post('/api/v1/admin/blocks/' + block.id + '/cancel', {version: block.version});
      openBookingPage(path, 'Блокировка снята. Расписание обновлено.');
    } catch (failure) {
      if (failure.status === 401) location.assign('/login');
      else if (failure.status === 409) openBookingPage(path, failure.message);
      else if (!failure.status || failure.status >= 500) {
        openBookingPage(path, 'Проверьте актуальное расписание.');
      } else {
        message(error, failure.message);
        saving = false;
        for (const button of buttons) button.disabled = false;
      }
    }
  });
}
