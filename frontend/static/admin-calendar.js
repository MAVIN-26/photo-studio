const calendar = document.querySelector('[data-admin-calendar]');
const toggle = calendar.querySelector('.admin-calendar-toggle');
const panel = calendar.querySelector('.admin-calendar-panel');
const days = calendar.querySelector('[data-calendar-days]');
const title = calendar.querySelector('[data-calendar-month]');
const previous = calendar.querySelector('[data-month-step="-1"]');
const next = calendar.querySelector('[data-month-step="1"]');
const dateForm = document.querySelector('.admin-date-form');
const monthLabel = new Intl.DateTimeFormat('ru-RU', {month: 'long', year: 'numeric', timeZone: 'UTC'});
const dayLabel = new Intl.DateTimeFormat('ru-RU', {dateStyle: 'full', timeZone: 'UTC'});
const selected = calendar.dataset.date;
const month = new Date(selected.slice(0, 8) + '01T00:00:00Z');

function renderMonth() {
  title.textContent = monthLabel.format(month);
  previous.disabled = month.getUTCFullYear() === 1 && month.getUTCMonth() === 0;
  next.disabled = month.getUTCFullYear() === 9999 && month.getUTCMonth() === 11;
  const current = new Date(month);
  const cells = Array.from({length: (current.getUTCDay() + 6) % 7}, () =>
    document.createElement('span'));
  while (current.getUTCMonth() === month.getUTCMonth()) {
    const value = current.toISOString().slice(0, 10);
    const link = document.createElement('a');
    link.href = '/admin?date=' + value;
    link.textContent = current.getUTCDate();
    link.setAttribute('aria-label', dayLabel.format(current));
    if (value === selected) link.setAttribute('aria-current', 'date');
    if (value === calendar.dataset.today) link.classList.add('is-today');
    cells.push(value === '9999-12-31' ? document.createElement('span') : link);
    current.setUTCDate(current.getUTCDate() + 1);
  }
  days.replaceChildren(...cells);
}

function setOpen(open, restoreFocus = true) {
  panel.hidden = !open;
  toggle.setAttribute('aria-expanded', String(open));
  if (open) (days.querySelector('[aria-current]') ?? days.querySelector('a'))?.focus();
  else if (restoreFocus) toggle.focus();
}

for (const button of [previous, next]) {
  button.addEventListener('click', () => {
    month.setUTCMonth(month.getUTCMonth() + Number(button.dataset.monthStep));
    renderMonth();
    if (button.disabled) (button === previous ? next : previous).focus();
  });
}
toggle.addEventListener('click', () => setOpen(panel.hidden));
calendar.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !panel.hidden) {
    event.preventDefault();
    setOpen(false);
  }
});
document.addEventListener('click', event => {
  if (!panel.hidden && !calendar.contains(event.target)) setOpen(false, false);
});
calendar.addEventListener('focusout', event => {
  if (!panel.hidden && event.relatedTarget && !calendar.contains(event.relatedTarget)) {
    setOpen(false, false);
  }
});
renderMonth();
dateForm.hidden = true;
calendar.hidden = false;
