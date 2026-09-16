/**
 * CTF participant walkthrough page.
 *
 * Copies the prompt text out of each step's <pre> block to the clipboard and
 * shows brief "Copied!" feedback on the button.
 *
 * Extracted from the inline <script> in
 * templates/ctf/participant/walkthrough.html so the template stays within
 * SonarCloud's Web:LongJavaScriptCheck limit.
 */

function copyPrompt(btn) {
    const promptBlock = btn.closest('.wt-prompt-block');
    const text = promptBlock.querySelector('pre').textContent.trim().replace(/\s+/g, ' ');
    navigator.clipboard.writeText(text).then(function () {
        btn.textContent = 'Copied!';
        btn.classList.add('copied');
        setTimeout(function () {
            btn.textContent = 'Copy';
            btn.classList.remove('copied');
        }, 2000);
    });
}

globalThis.copyPrompt = copyPrompt;
