const gallery = document.querySelector('.room-gallery');
const controls = gallery?.querySelector('.room-gallery-controls');

if (controls) {
  const images = [...gallery.querySelectorAll('img')];
  const number = controls.querySelector('[data-image-number]');
  let index = 0;

  function goToImage(step) {
    images[index].hidden = true;
    index = (index + step + images.length) % images.length;
    images[index].hidden = false;
    number.textContent = (index + 1) + ' / ' + images.length;
  }

  controls.querySelector('[data-previous]').addEventListener('click', () => goToImage(-1));
  controls.querySelector('[data-next]').addEventListener('click', () => goToImage(1));
  controls.hidden = false;
}
