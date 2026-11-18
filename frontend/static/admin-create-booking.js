import { getJson, openBookingPage } from './booking-http.js';

export function initManualBooking({grid, localDate, timeFormat, priceFormat, pathFor}) {
  const drawer = document.querySelector('#admin-create-booking');
  if (!drawer) return;

  const form = drawer.querySelector('form');
  const {room, day, start, hours, contact_name, contact_phone, source, comment} = form.elements;
  const submit = form.querySelector('[type=submit]');
  const error = form.querySelector('[role=alert]');
  const availability = form.querySelector('[data-create-availability]');
  const retry = form.querySelector('[data-create-retry]');
  const total = form.querySelector('[data-create-total]');
  const calculation = form.querySelector('[data-create-calculation]');
  const triggers = [...document.querySelectorAll('[data-new-booking]')];
  const closeButtons = [...drawer.querySelectorAll('[data-close]')];
  const dateFields = [room, day, start, hours];
  const hourMs = 3600000;
  let activeRequest;
  let snapshot;
  let saving = false;
  let outcomeUnknown = false;

  function setError(message = '') {
    error.hidden = !message;
    error.textContent = message;
  }

  function timestamp(time) {
    return day.value + 'T' + time + ':00+03:00';
  }

  function firstConflict(startsAt, endsAt) {
    return snapshot.entries.find(entry =>
      Date.parse(entry.starts_at) < endsAt && Date.parse(entry.ends_at) > startsAt
    );
  }

  function describeConflict(entry, startsAt) {
    const starts = Math.max(startsAt, Date.parse(entry.starts_at));
    const reason = entry.contact_name ? 'бронь · ' + entry.contact_name
      : entry.reason === 'cleaning' ? 'уборка' : 'ремонт';
    return 'Зал занят с ' + timeFormat.format(new Date(starts)) + ' · ' + reason +
      '. Уменьшите число часов или выберите другое время.';
  }

  function refreshSummary(feedback = '') {
    const duration = hours.valueAsNumber;
    const validDuration = hours.validity.valid && Number.isInteger(duration);
    const rate = snapshot?.room.hourly_price_minor;
    calculation.textContent = snapshot && validDuration
      ? priceFormat.format(rate / 100) + ' × ' + duration + ' ч' : '';
    total.textContent = snapshot && validDuration ? priceFormat.format(rate * duration / 100) : '—';
    submit.disabled = true;
    hours.removeAttribute('aria-invalid');
    setError(feedback);
    if (!snapshot || !start.value || !validDuration || saving || outcomeUnknown) return;

    const startsAt = Date.parse(timestamp(start.value));
    const endsAt = startsAt + duration * hourMs;
    const conflict = firstConflict(startsAt, endsAt);
    if (endsAt > Date.parse(timestamp(snapshot.room.closes_at))) {
      hours.setAttribute('aria-invalid', 'true');
      setError('Интервал выходит за часы работы зала. Уменьшите число часов.');
    } else if (conflict) {
      hours.setAttribute('aria-invalid', 'true');
      setError(describeConflict(conflict, startsAt));
    } else if (startsAt <= snapshot.now) {
      setError('Этот час уже начался. Выберите другое время.');
    } else {
      submit.disabled = false;
    }
  }

  async function loadSchedule(preferredStart = '', feedback = '') {
    activeRequest?.abort();
    const request = new AbortController();
    activeRequest = request;
    snapshot = undefined;
    start.replaceChildren();
    start.disabled = true;
    retry.hidden = true;
    refreshSummary(feedback);
    availability.textContent = '';
    if (!day.value || !day.checkValidity()) return;
    availability.textContent = 'Загрузка доступности…';
    const query = new URLSearchParams({date_from: day.value, date_to: day.value, room_id: room.value});

    try {
      const result = await getJson('/api/v1/admin/schedule?' + query, {signal: request.signal});
      if (request.signal.aborted) return;
      const selectedRoom = result.rooms[0];
      snapshot = {
        room: selectedRoom,
        now: Date.parse(result.server_now),
        entries: [...result.bookings, ...result.blocks]
          .sort((first, second) => Date.parse(first.starts_at) - Date.parse(second.starts_at)),
      };
      const opening = Number(selectedRoom.opens_at.slice(0, 2));
      const closing = Number(selectedRoom.closes_at.slice(0, 2));
      for (let hour = opening; hour < closing; hour += 1) {
        const value = String(hour).padStart(2, '0') + ':00';
        const startsAt = Date.parse(timestamp(value));
        const conflict = firstConflict(startsAt, startsAt + hourMs);
        const free = startsAt > snapshot.now && !conflict;
        if (free || value === preferredStart) {
          start.add(new Option(value + (conflict ? ' · занято' : ''), value));
        }
      }
      if ([...start.options].some(option => option.value === preferredStart)) {
        start.value = preferredStart;
      }
      availability.textContent = start.options.length ? '' : 'В этот день нет свободного времени.';
      start.disabled = !start.options.length;
      refreshSummary(feedback);
    } catch (failure) {
      if (request.signal.aborted) return;
      availability.textContent = '';
      if (failure.status === 401) {
        location.assign('/login');
        return;
      }
      setError(failure.status ? failure.message : 'Не удалось загрузить доступность.');
      retry.hidden = false;
    }
  }

  function open(trigger) {
    form.reset();
    for (const field of form.querySelectorAll('[aria-invalid]')) field.removeAttribute('aria-invalid');
    outcomeUnknown = false;
    if (trigger.dataset.roomId) room.value = trigger.dataset.roomId;
    day.value = grid.dataset.day >= day.min && grid.dataset.day <= day.max ? grid.dataset.day : day.min;
    const preferredStart = trigger.dataset.hour
      ? String(trigger.dataset.hour).padStart(2, '0') + ':00' : '';
    drawer.showModal();
    loadSchedule(preferredStart);
  }

  function lockForm(locked) {
    saving = locked;
    for (const control of [...dateFields, contact_name, contact_phone, source, comment, ...closeButtons]) {
      control.disabled = locked;
    }
    submit.disabled = locked;
  }

  function showValidationError(failure) {
    const detail = failure.details?.find(item => form.elements.namedItem(item.field));
    setError(detail?.message || failure.message);
    if (detail) {
      const field = form.elements.namedItem(detail.field);
      field.setAttribute('aria-invalid', 'true');
      field.focus();
    }
  }

  for (const trigger of triggers) {
    if (!trigger.dataset.roomId) trigger.disabled = false;
    trigger.addEventListener('click', () => open(trigger));
  }
  for (const button of closeButtons) button.addEventListener('click', () => drawer.close());
  drawer.addEventListener('close', () => activeRequest?.abort());
  drawer.addEventListener('cancel', event => {
    if (saving) event.preventDefault();
  });
  room.addEventListener('change', () => loadSchedule());
  day.addEventListener('change', () => loadSchedule());
  start.addEventListener('change', () => refreshSummary());
  hours.addEventListener('input', () => refreshSummary());
  retry.addEventListener('click', () => loadSchedule(start.value));
  form.addEventListener('input', event => {
    if (event.target !== hours) event.target.removeAttribute('aria-invalid');
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (saving || outcomeUnknown || submit.disabled) return;
    const chosenStart = start.value;
    const startsAt = timestamp(chosenStart);
    const body = {
      room_id: room.value, room_version: snapshot.room.version,
      starts_at: startsAt,
      ends_at: new Date(Date.parse(startsAt) + hours.valueAsNumber * hourMs).toISOString(),
      contact_name: contact_name.value, contact_phone: contact_phone.value,
      source: source.value, comment: comment.value,
    };
    lockForm(true);
    let sent = false;
    try {
      const csrf = await getJson('/api/v1/auth/csrf');
      sent = true;
      const created = await getJson('/api/v1/admin/bookings', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf.csrf_token},
        body: JSON.stringify(body),
      });
      openBookingPage(pathFor(created.id, localDate(created.starts_at)), created.message);
    } catch (failure) {
      if (failure.status === 401) {
        location.assign('/login');
        return;
      }
      lockForm(false);
      if (sent && (!failure.status || failure.status >= 500)) {
        outcomeUnknown = true;
        refreshSummary('Результат сохранения неизвестен. Обновите шахматку и проверьте запись.');
        return;
      }
      if (['SLOT_UNAVAILABLE', 'ROOM_SETTINGS_CHANGED', 'INVALID_TIME_RANGE'].includes(failure.code)) {
        await loadSchedule(chosenStart, failure.message);
      } else {
        refreshSummary();
        showValidationError(failure);
      }
    }
  });
}
