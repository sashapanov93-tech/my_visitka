document.addEventListener('DOMContentLoaded', () => {
  const languageButtons = document.querySelectorAll('[data-lang]');
  const translatable = document.querySelectorAll('[data-ru][data-en]');
  const notice = document.getElementById('notice');

  const setLanguage = (lang) => {
    document.documentElement.lang = lang;
    translatable.forEach((element) => { element.textContent = element.dataset[lang]; });
    languageButtons.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.lang === lang)));
    localStorage.setItem('site-language', lang);
  };

  languageButtons.forEach((button) => button.addEventListener('click', () => setLanguage(button.dataset.lang)));
  setLanguage(localStorage.getItem('site-language') === 'en' ? 'en' : 'ru');

  document.querySelectorAll('[data-modal]').forEach((button) => {
    button.addEventListener('click', () => document.getElementById(button.dataset.modal).showModal());
  });
  document.querySelectorAll('[data-close]').forEach((button) => {
    button.addEventListener('click', () => button.closest('dialog').close());
  });
  document.querySelectorAll('dialog').forEach((dialog) => {
    dialog.addEventListener('click', (event) => { if (event.target === dialog) dialog.close(); });
  });
  document.querySelectorAll('[data-request-form]').forEach((form) => {
    form.addEventListener('submit', () => {
      form.reset();
      notice.textContent = document.documentElement.lang === 'en' ? 'Thanks! Your request has been received.' : 'Спасибо! Ваша заявка принята.';
      notice.hidden = false;
      window.setTimeout(() => { notice.hidden = true; }, 4000);
    });
  });
});
