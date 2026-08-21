document.addEventListener('DOMContentLoaded', () => {
  const languageButtons = document.querySelectorAll('[data-lang]');
  const translatable = document.querySelectorAll('[data-ru][data-en]');
  const notice = document.getElementById('notice');

  // После создания backend в Render замени только адрес ниже.
  const CONTACT_API_URL = 'https://my-visitka-api.onrender.com/api/contact';

  const setLanguage = (lang) => {
    document.documentElement.lang = lang;

    translatable.forEach((element) => {
      element.textContent = element.dataset[lang];
    });

    languageButtons.forEach((button) => {
      button.setAttribute(
        'aria-pressed',
        String(button.dataset.lang === lang)
      );
    });

    localStorage.setItem('site-language', lang);
  };

  languageButtons.forEach((button) => {
    button.addEventListener('click', () => {
      setLanguage(button.dataset.lang);
    });
  });

  setLanguage(localStorage.getItem('site-language') === 'en' ? 'en' : 'ru');

  // Открытие модальных окон заявок.
  document.querySelectorAll('[data-modal]').forEach((button) => {
    button.addEventListener('click', () => {
      const modalId = button.dataset.modal;
      const dialog = document.getElementById(modalId);

      if (!dialog) {
        console.error(`Dialog not found: ${modalId}`);
        return;
      }

      if (typeof dialog.showModal === 'function') {
        dialog.showModal();
      } else {
        dialog.setAttribute('open', '');
      }
    });
  });

  // Закрытие по кнопке ×.
  document.querySelectorAll('[data-close]').forEach((button) => {
    button.addEventListener('click', () => {
      const dialog = button.closest('dialog');
      if (dialog) dialog.close();
    });
  });

  // Закрытие по клику на затемнённый фон.
  document.querySelectorAll('dialog').forEach((dialog) => {
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) {
        dialog.close();
      }
    });
  });

  const showNotice = (ok, status = 0) => {
    let text;

    if (ok) {
      text = document.documentElement.lang === 'en'
        ? 'Thanks! Your request has been received.'
        : 'Спасибо! Ваша заявка принята.';
    } else if (status === 429) {
      text = document.documentElement.lang === 'en'
        ? 'Too many requests. Please try again later.'
        : 'Слишком много запросов. Попробуйте немного позже.';
    } else {
      text = document.documentElement.lang === 'en'
        ? 'Error sending request. Please try again.'
        : 'Ошибка отправки. Попробуйте ещё раз.';
    }

    notice.textContent = text;
    notice.hidden = false;

    window.setTimeout(() => {
      notice.hidden = true;
    }, 4500);
  };

  document.querySelectorAll('[data-request-form]').forEach((form) => {
    // Honeypot для простых спам-ботов.
    const honeypot = document.createElement('input');
    honeypot.type = 'text';
    honeypot.name = 'website';
    honeypot.tabIndex = -1;
    honeypot.autocomplete = 'off';
    honeypot.setAttribute('aria-hidden', 'true');
    honeypot.className = 'hp-field';
    form.appendChild(honeypot);

    form.addEventListener('submit', async (event) => {
      event.preventDefault();

      const dialog = form.closest('dialog');
      const submitButton = form.querySelector('[type="submit"]');
      const formData = new FormData(form);
      const title = form.querySelector('h2')?.textContent || 'Заявка';

      if (CONTACT_API_URL.includes('YOUR-BACKEND')) {
        console.error('CONTACT_API_URL is not configured');
        showNotice(false);
        return;
      }

      const payload = {
        form_type: title,
        name: formData.get('name') || '',
        email: formData.get('email') || '',
        contact: formData.get('contact') || '',
        link: formData.get('link') || '',
        message: formData.get('message') || formData.get('request') || '',
        website: formData.get('website') || ''
      };

      if (submitButton) {
        submitButton.disabled = true;
      }

      try {
        const response = await fetch(CONTACT_API_URL, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          body: JSON.stringify(payload)
        });

        if (!response.ok) {
          showNotice(false, response.status);
          return;
        }

        form.reset();

        if (dialog) {
          dialog.close();
        }

        showNotice(true);
      } catch (error) {
        console.error('Contact form error:', error);
        showNotice(false);
      } finally {
        if (submitButton) {
          submitButton.disabled = false;
        }
      }
    });
  });
});
