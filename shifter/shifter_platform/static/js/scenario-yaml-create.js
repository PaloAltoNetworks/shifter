/**
 * Scenario editor - "Create from YAML" page.
 *
 * Adds two-space Tab indentation inside the YAML editor and validates the
 * document asynchronously against the scenario_editor validate endpoint.
 *
 * Extracted from the inline <script> in
 * templates/scenario_editor/yaml_create.html so the template stays within
 * SonarCloud's Web:LongJavaScriptCheck limit. The validate endpoint URL is
 * read from the editor's data-validate-url attribute; the CSRF token is read
 * from the form's rendered csrfmiddlewaretoken field.
 */

function getCsrfToken() {
    const field = document.querySelector('[name=csrfmiddlewaretoken]');
    return field ? field.value : '';
}

function renderValidationErrors(resultDiv, errors) {
    resultDiv.className = 'validation-result validation-invalid';
    resultDiv.textContent = '';
    const strong = document.createElement('strong');
    strong.textContent = 'Validation errors:';
    resultDiv.appendChild(strong);
    const ul = document.createElement('ul');
    ul.style.cssText = 'margin: 4px 0 0 16px;';
    errors.forEach(function (e) {
        const li = document.createElement('li');
        li.textContent = e;
        ul.appendChild(li);
    });
    resultDiv.appendChild(ul);
}

function validateYAML() {
    const editor = document.getElementById('yamlEditor');
    const yamlContent = editor.value;
    const resultDiv = document.getElementById('validationResult');

    fetch(editor.dataset.validateUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken(),
        },
        body: JSON.stringify({ yaml_content: yamlContent }),
    })
        .then(function (response) { return response.json(); })
        .then(function (data) {
            resultDiv.style.display = 'block';
            if (data.valid) {
                resultDiv.className = 'validation-result validation-valid';
                resultDiv.textContent = 'Valid scenario definition.';
            } else {
                renderValidationErrors(resultDiv, data.errors);
            }
        })
        .catch(function (err) {
            resultDiv.style.display = 'block';
            resultDiv.className = 'validation-result validation-invalid';
            resultDiv.textContent = 'Error validating: ' + err.message;
        });
}

document.addEventListener('DOMContentLoaded', function () {
    const editor = document.getElementById('yamlEditor');
    if (!editor) return;
    editor.addEventListener('keydown', function (e) {
        if (e.key === 'Tab') {
            e.preventDefault();
            const start = this.selectionStart;
            const end = this.selectionEnd;
            this.value = this.value.substring(0, start) + '  ' + this.value.substring(end);
            this.selectionStart = this.selectionEnd = start + 2;
        }
    });
});

globalThis.validateYAML = validateYAML;
