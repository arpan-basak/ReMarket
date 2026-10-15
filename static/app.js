document.addEventListener('DOMContentLoaded', () => {
  const menuButton = document.querySelector('.menu-toggle');
  const mobileMenu = document.querySelector('.mobile-menu');
  if (menuButton && mobileMenu) {
    menuButton.addEventListener('click', () => {
      const open = menuButton.getAttribute('aria-expanded') === 'true';
      menuButton.setAttribute('aria-expanded', String(!open));
      mobileMenu.hidden = open;
    });
  }

  const title = document.querySelector('#title');
  const price = document.querySelector('#price');
  const location = document.querySelector('#location');
  const photo = document.querySelector('#photo');
  if (title && price && location) {
    const setText = (selector, value) => { const element = document.querySelector(selector); if (element) element.textContent = value; };
    const update = () => {
      setText('#preview-title', title.value.trim() || 'Your item title');
      setText('#preview-price', price.value ? '$' + Number(price.value).toLocaleString(undefined, { maximumFractionDigits: 2 }) : '$0');
      setText('#preview-location', location.value.trim() || 'Pickup area');
    };
    [title, price, location].forEach(element => element.addEventListener('input', update));
    update();
  }
  if (photo) {
    photo.addEventListener('change', () => {
      const file = photo.files && photo.files[0];
      if (!file) return;
      const url = URL.createObjectURL(file);
      const main = document.querySelector('#photo-preview');
      const imageBox = document.querySelector('#preview-image');
      if (main) { main.src = url; main.hidden = false; }
      const prompt = document.querySelector('#photo-prompt');
      if (prompt) prompt.hidden = true;
      if (imageBox) { imageBox.replaceChildren(Object.assign(document.createElement('img'), { src: url, alt: 'Listing preview' })); }
    });
  }
  document.querySelectorAll('[data-gallery-src]').forEach(button => {
    button.addEventListener('click', () => {
      const image = document.querySelector('#product-main-image');
      if (!image) return;
      image.src = button.dataset.gallerySrc;
      document.querySelectorAll('[data-gallery-src]').forEach(item => item.classList.toggle('selected', item === button));
    });
  });
});
