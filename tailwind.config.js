module.exports = {
  content: ["./templates/**/*.html", "./static/**/*.js"],
  safelist: [
    {pattern: /bg-modern-.*/},
    {pattern: /text-modern-.*/},
    {pattern: /border-modern-.*/},
    {pattern: /from-modern-.*/},
    {pattern: /to-modern-.*/},
    {pattern: /ring-modern-.*/},
  ],
  theme: {
    extend: {
      colors: {
        'modern-green': '#00ff88',
        'modern-cyan': '#00d4ff',
        'modern-purple': '#b47aff',
        'modern-pink': '#ff6b9d',
        'modern-dark': '#0a0a0f',
        'modern-darker': '#050508',
        'modern-card': '#13131a'
      }
    }
  },
  plugins: []
}
