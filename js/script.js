document.addEventListener('DOMContentLoaded', () => {
  const languageButtons = document.querySelectorAll('[data-lang]');
  const translatable = document.querySelectorAll('[data-ru][data-en]');
  const notice = document.getElementById('notice');

  // Replace with the public URL of the separate Render backend.
  const CONTACT_API_URL = 'https://YOUR-REQUEST-BACKEND.onrender.com/api/contact';

  const setLanguage = (lang) => {
    document.documentElement.lang = lang;
    translatable.forEach((element) => {
      element.textContent = element.dataset[lang];
    });
    languageButtons.forEach((button) => {
      button.setAttribute('aria-pressed', String(button.dataset.lang === lang));
    });
    localStorage.setItem('site-language', lang);
  };

  languageButtons.forEach((button) => {
    button.addEventListener('click', () => setLanguage(button.dataset.lang));
  });

  setLanguage(localStorage.getItem('site-language') === 'en' ? 'en' : 'ru');

  document.querySelectorAll('[data-modal]').forEach((button) => {
    button.addEventListener('click', () => {
      document.getElementById(button.dataset.modal).showModal();
    });
  });

  document.querySelectorAll('[data-close]').forEach((button) => {
    button.addEventListener('click', () => button.closest('dialog').close());
  });

  document.querySelectorAll('dialog').forEach((dialog) => {
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) dialog.close();
    });
  });

  const showNotice = (ok) => {
    notice.textContent = ok
      ? (document.documentElement.lang === 'en'
          ? 'Thanks! Your request has been received.'
          : 'Спасибо! Ваша заявка принята.')
      : (document.documentElement.lang === 'en'
          ? 'Error sending request. Please try again.'
          : 'Ошибка отправки. Попробуйте ещё раз.');
    notice.hidden = false;
    window.setTimeout(() => {
      notice.hidden = true;
    }, 4000);
  };

  document.querySelectorAll('[data-request-form]').forEach((form) => {
    // Honeypot field added dynamically so normal visitors never see it.
    const honeypot = document.createElement('input');
    honeypot.type = 'text';
    honeypot.name = 'website';
    honeypot.tabIndex = -1;
    honeypot.autocomplete = 'off';
    honeypot.setAttribute('aria-hidden', 'true');
    honeypot.style.position = 'absolute';
    honeypot.style.left = '-9999px';
    form.appendChild(honeypot);

    form.addEventListener('submit', async (event) => {
      event.preventDefault();

      const dialog = form.closest('dialog');
      const submitButton = form.querySelector('[type="submit"]');
      const formData = new FormData(form);
      const title = form.querySelector('h2')?.textContent || 'Заявка';

      const payload = {
        form_type: title,
        name: formData.get('name') || '',
        email: formData.get('email') || '',
        contact: formData.get('contact') || '',
        link: formData.get('link') || '',
        message: formData.get('message') || formData.get('request') || '',
        website: formData.get('website') || '',
      };

      if (submitButton) submitButton.disabled = true;

      try {
        const response = await fetch(CONTACT_API_URL, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify(payload),
        });

        if (!response.ok) throw new Error(`HTTP ${response.status}`);

        dialog.close();
        form.reset();
        showNotice(true);
      } catch (error) {
        console.error('Contact form error:', error);
        showNotice(false);
      } finally {
        if (submitButton) submitButton.disabled = false;
      }
    });
  });
});
