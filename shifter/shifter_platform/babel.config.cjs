// Babel config for jest only: transforms the ESM static/js sources (which the
// browser loads natively as <script type="module">) to CommonJS so jest can
// require them. Production serves the untransformed ES modules.
module.exports = {
    presets: [["@babel/preset-env", { targets: { node: "current" } }]],
};
