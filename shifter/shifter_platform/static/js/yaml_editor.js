// Scenario YAML editor: tab-key soft-indent + async validation.
// Extracted from the inline <script> in
// templates/scenario_editor/yaml_editor.html so the template stays
// within Sonar Web:LongJavaScriptCheck limits. Behavior is unchanged;
// the validate endpoint is read from the #validationResult element's
// data-validate-url attribute.

function initYamlEditor() {
    var editor = document.getElementById('yamlEditor');
    if (!editor) return;
    editor.addEventListener('keydown', function (e) {
        if (e.key === 'Tab') {
            e.preventDefault();
            var start = this.selectionStart;
            var end = this.selectionEnd;
            this.value = this.value.substring(0, start) + '  ' + this.value.substring(end);
            this.selectionStart = this.selectionEnd = start + 2;
        }
    });
}

function validateYAML() {
    var yaml_content = document.getElementById('yamlEditor').value;
    var resultDiv = document.getElementById('validationResult');

    fetch(resultDiv.dataset.validateUrl, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': document.querySelector('[name=csrfmiddlewaretoken]').value,
        },
        body: JSON.stringify({ yaml_content: yaml_content }),
    })
    .then(function (response) { return response.json(); })
    .then(function (data) {
        resultDiv.style.display = 'block';
        if (data.valid) {
            resultDiv.className = 'validation-result validation-valid';
            resultDiv.textContent = 'Valid scenario definition.';
        } else {
            resultDiv.className = 'validation-result validation-invalid';
            resultDiv.textContent = '';
            var strong = document.createElement('strong');
            strong.textContent = 'Validation errors:';
            resultDiv.appendChild(strong);
            var ul = document.createElement('ul');
            ul.style.cssText = 'margin: 4px 0 0 16px;';
            data.errors.forEach(function (e) {
                var li = document.createElement('li');
                li.textContent = e;
                ul.appendChild(li);
            });
            resultDiv.appendChild(ul);
        }
    })
    .catch(function (err) {
        resultDiv.style.display = 'block';
        resultDiv.className = 'validation-result validation-invalid';
        resultDiv.textContent = 'Error validating: ' + err.message;
    });
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initYamlEditor);
} else {
    initYamlEditor();
}

globalThis.validateYAML = validateYAML;
