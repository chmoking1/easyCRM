// The acknowledgement keeps the primary action clear while its full form is built next.
const soonButton = document.querySelector('[data-soon-button]');
const soonMessage = document.querySelector('.soon-message');

// Guarding against missing elements lets this script fail safely if the template evolves.
if (soonButton && soonMessage) {
  soonButton.addEventListener('click', () => {
    soonMessage.textContent = 'Форма добавления сотрудника появится следующим шагом.';
  });
}
