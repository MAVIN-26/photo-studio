import { getJson } from './booking-http.js';

const form = document.querySelector('#room-settings');
const save = form.querySelector('button[type=submit]');
const summary = form.querySelector('.room-settings-summary');
const priceFormat = new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 2});
const priceField = 'hourly_price_minor';
const openingField = 'opens_at';
const closingField = 'closes_at';
const fieldNames = [priceField, openingField, closingField];
const maxPriceMinor = 2147483647;
let saving = false;

const cards = [...form.querySelectorAll('[data-room-id]')].map(element => {
  const fields = Object.fromEntries(fieldNames.map(name => [name, element.querySelector('[name="' + name + '"]')]));
  return {
    id: element.dataset.roomId,
    version: Number(element.dataset.version),
    fields,
    fieldset: element.querySelector('fieldset'),
    original: {
      [priceField]: Number(element.dataset.price),
      [openingField]: fields[openingField].value,
      [closingField]: fields[closingField].value,
    },
    badge: element.querySelector('.room-settings-badge'),
    error: element.querySelector('.room-settings-error'),
    feedback: element.querySelector('.room-settings-feedback'),
    reload: element.querySelector('[data-refresh-room]'),
    needsReload: false,
    loading: false,
  };
});

function priceMinor(value) {
  const match = /^(\d+)(?:[,.](\d{1,2}))?$/.exec(value.replace(/[ \u00a0\u202f]/g, ''));
  if (!match) return NaN;
  return Number(match[1]) * 100 + Number((match[2] || '').padEnd(2, '0'));
}

function edits(card) {
  const values = {
    [priceField]: priceMinor(card.fields[priceField].value),
    [openingField]: card.fields[openingField].value,
    [closingField]: card.fields[closingField].value,
  };
  return Object.fromEntries(fieldNames
    .filter(name => values[name] !== card.original[name])
    .map(name => [name, values[name]]));
}

function show(element, message = '') {
  element.textContent = message;
  element.hidden = !message;
}

function showError(card, message = '', invalidFields = []) {
  show(card.error, message);
  for (const name of fieldNames) {
    if (invalidFields.includes(name)) card.fields[name].setAttribute('aria-invalid', 'true');
    else card.fields[name].removeAttribute('aria-invalid');
  }
}

function render() {
  let canSave = false;
  for (const card of cards) {
    const changed = Object.keys(edits(card)).length > 0;
    card.badge.hidden = !changed;
    card.fieldset.disabled = saving || card.loading;
    card.reload.hidden = !card.needsReload;
    card.reload.disabled = saving || card.loading;
    canSave ||= changed && !card.needsReload && !card.loading;
  }
  save.disabled = saving || !canSave;
}

function readPayload(card) {
  const changes = edits(card);
  const values = {...card.original, ...changes};
  if (!Number.isInteger(values[priceField]) || values[priceField] <= 0 || values[priceField] > maxPriceMinor) {
    showError(card, 'Укажите положительную цену, до двух знаков после запятой.', [priceField]);
    return null;
  }
  if (values[openingField] >= values[closingField]) {
    showError(card, 'Время открытия должно быть раньше времени закрытия.', [openingField, closingField]);
    return null;
  }
  return {...changes, version: card.version};
}

function applyVersion(card, room, preserve = []) {
  card.version = room.version;
  for (const name of fieldNames) {
    card.original[name] = room[name];
    if (preserve.includes(name)) continue;
    card.fields[name].value = name === priceField ? priceFormat.format(room[name] / 100) : room[name];
  }
  card.needsReload = false;
}

function failCard(card, failure) {
  const details = Array.isArray(failure.details) ? failure.details : [];
  const fields = details.map(item => item.field).filter(name => fieldNames.includes(name));
  const detailsMessage = details.find(item => fieldNames.includes(item.field))?.message;
  const hoursConflict = ['INVALID_TIME_RANGE', 'ROOM_SCHEDULE_CONFLICT'].includes(failure.code);
  card.needsReload = failure.code === 'VERSION_CONFLICT' || !failure.status || failure.status >= 500;
  const message = !failure.status || failure.status >= 500
    ? 'Результат сохранения неизвестен. Загрузите актуальные настройки.'
    : detailsMessage || failure.message;
  showError(card, message, hoursConflict ? [openingField, closingField] : fields);
}

for (const card of cards) {
  for (const field of Object.values(card.fields)) {
    field.addEventListener('input', () => {
      if (!card.needsReload) showError(card);
      show(card.feedback);
      show(summary);
      render();
    });
  }
  card.reload.addEventListener('click', async () => {
    const pending = Object.keys(edits(card));
    card.loading = true;
    render();
    try {
      const room = await getJson('/api/v1/rooms/' + card.id);
      applyVersion(card, room, pending);
      showError(card);
      show(card.feedback, 'Актуальные настройки · ' + priceFormat.format(room.hourly_price_minor / 100) +
        ' ₽/ч, ' + room.opens_at + '–' + room.closes_at + '. Проверьте правки перед сохранением.');
    } catch {
      showError(card, 'Не удалось загрузить актуальные настройки.');
    } finally {
      card.loading = false;
      render();
    }
  });
}

form.addEventListener('submit', async event => {
  event.preventDefault();
  if (saving) return;
  const changed = cards.filter(card =>
    !card.needsReload && !card.loading && Object.keys(edits(card)).length > 0);
  const updates = changed.map(card => {
    show(card.feedback);
    return {card, payload: readPayload(card)};
  }).filter(update => update.payload);
  if (!updates.length) {
    if (changed.length) show(summary, 'Проверьте поля в отмеченных карточках.');
    return;
  }

  saving = true;
  render();
  let saved = 0;
  try {
    const csrf = await getJson('/api/v1/auth/csrf');
    for (const {card, payload} of updates) {
      try {
        const room = await getJson('/api/v1/admin/rooms/' + card.id, {
          method: 'PATCH',
          headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf.csrf_token},
          body: JSON.stringify(payload),
        });
        applyVersion(card, room);
        showError(card);
        show(card.feedback, 'Сохранено · ' + priceFormat.format(room.hourly_price_minor / 100) +
          ' ₽/ч, ' + room.opens_at + '–' + room.closes_at);
        saved += 1;
      } catch (failure) {
        failCard(card, failure);
      }
    }
    const remaining = cards.filter(card => Object.keys(edits(card)).length || card.needsReload).length;
    show(summary, remaining ? 'Сохранено залов: ' + saved + '. Осталось проверить: ' + remaining + '.'
      : 'Изменения сохранены.');
  } catch (failure) {
    show(summary, failure.status ? failure.message : 'Не удалось подключиться. Повторите попытку.');
  } finally {
    saving = false;
    render();
  }
});

render();
