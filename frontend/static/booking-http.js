export async function getJson(url, options) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (response.ok) return body;
  const failure = new Error(body.error?.message || 'Не удалось выполнить запрос.');
  failure.status = response.status;
  failure.code = body.error?.code;
  failure.details = body.error?.details;
  throw failure;
}

export function openBookingPage(path, message) {
  try {
    sessionStorage.setItem('lumenbook.booking-notice.' + path, message);
  } catch {
    // Навигация должна сработать и при недоступном хранилище.
  }
  if (location.pathname + location.search === path) location.reload();
  else location.assign(path);
}
