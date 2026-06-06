/**
 * ChoiceBox — presents options, returns chosen option object.
 */
export class ChoiceBox {
  constructor(root) {
    this.box     = root.querySelector('#choice-box');
    this.prompt  = root.querySelector('#choice-prompt');
    this.options = root.querySelector('#choice-options');
  }

  show(optionList, promptText = '') {
    return new Promise(resolve => {
      this.prompt.textContent = promptText;
      this.options.innerHTML  = '';
      this.box.classList.remove('hidden');

      optionList.forEach((opt, i) => {
        const btn = document.createElement('button');
        btn.className = 'choice-option';
        btn.textContent = opt.text;
        btn.addEventListener('click', () => resolve(opt), { once: true });
        this.options.appendChild(btn);
      });
    });
  }

  hide() {
    this.box.classList.add('hidden');
    this.options.innerHTML = '';
  }
}
