const form = document.querySelector('#auth-form');
const logoutButton = document.querySelector('[data-logout]');
const toggle = document.querySelector('.password-toggle');
let csrfToken;

function showError(field, message) {
  const mapped = ['email', 'phone'].includes(field) ? 'identifier' : field;
  const error = document.getElementById(`${mapped}-error`) || document.getElementById('form-error');
  const input = document.getElementById(mapped);
  if (input) input.setAttribute('aria-invalid', 'true');
  if (error) { error.textContent = message; error.hidden = false; }
}

async function loadCsrf() {
  const response = await fetch('/api/v1/auth/csrf', {credentials: 'same-origin', cache: 'no-store'});
  if (!response.ok) throw new Error('Не удалось подключиться к сервису. Обновите страницу.');
  csrfToken = (await response.json()).csrf_token;
}

if (toggle) {
  toggle.addEventListener('click', () => {
    const password = document.getElementById('password');
    const show = password.type === 'password';
    password.type = show ? 'text' : 'password';
    toggle.setAttribute('aria-pressed', String(show));
    toggle.setAttribute('aria-label', show ? 'Скрыть пароль' : 'Показать пароль');
  });
}

if (form) {
  const submit = form.querySelector('[type=submit]');
  loadCsrf().then(() => { submit.disabled = false; }).catch(error => showError('form', error.message));
  form.addEventListener('input', event => {
    event.target.removeAttribute('aria-invalid');
    const error = document.getElementById(`${event.target.name}-error`);
    if (error) error.hidden = true;
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (submit.disabled) return;
    form.querySelectorAll('.field-error, .form-error').forEach(error => { error.hidden = true; });
    form.querySelectorAll('[aria-invalid]').forEach(input => input.removeAttribute('aria-invalid'));
    const register = form.dataset.mode === 'register';
    const identifier = form.elements.identifier.value.trim();
    const password = form.elements.password.value;
    let valid = true;
    const invalid = (field, message) => { showError(field, message); valid = false; };
    if (!identifier) invalid('identifier', 'Введите телефон или email');
    if (!password) invalid('password', 'Введите пароль');
    if (register && password.length < 8) invalid('password', 'Пароль — не меньше 8 символов');
    if (register && !form.elements.name.value.trim()) invalid('name', 'Введите имя');
    if (register && !form.elements.consent.checked) invalid('consent', 'Без согласия на обработку персональных данных зарегистрироваться нельзя');
    if (!valid) { form.querySelector('[aria-invalid]')?.focus(); return; }
    const body = register ? {
      name: form.elements.name.value.trim(), password, consent: form.elements.consent.checked,
      [identifier.includes('@') ? 'email' : 'phone']: identifier,
    } : {identifier, password};
    submit.disabled = true;
    submit.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(`/api/v1/auth/${register ? 'register' : 'login'}`, {
        method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrfToken},
        body: JSON.stringify(body),
      });
      const result = await response.json();
      if (response.ok) {
        const bookingReturn = result.user.role === 'client' && form.dataset.bookingReturn;
        window.location.assign(bookingReturn || result.redirect_url);
        return;
      }
      const error = result.error;
      if (error.details?.length) error.details.forEach(item => showError(item.field, item.message));
      else showError(['INVALID_CREDENTIALS', 'IDENTIFIER_ALREADY_EXISTS'].includes(error.code) ? 'identifier' : 'form', error.message);
      if (error.code === 'CSRF_INVALID') await loadCsrf();
      form.querySelector('[aria-invalid]')?.focus();
    } catch {
      showError('form', 'Не удалось отправить форму. Проверьте соединение и повторите попытку.');
    } finally {
      submit.disabled = false;
      submit.removeAttribute('aria-busy');
    }
  });
}

if (logoutButton) {
  logoutButton.addEventListener('click', async () => {
    logoutButton.disabled = true;
    try {
      await loadCsrf();
      const response = await fetch('/api/v1/auth/logout', {
        method: 'POST', credentials: 'same-origin', headers: {'X-CSRF-Token': csrfToken},
      });
      if (!response.ok) throw new Error('Не удалось выйти. Повторите попытку.');
      window.location.assign('/login');
    } catch (error) {
      showError('form', error.message);
      logoutButton.disabled = false;
    }
  });
}
