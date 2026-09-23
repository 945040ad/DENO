import nextVitals from 'eslint-config-next/core-web-vitals';
import nextTs from 'eslint-config-next/typescript';

const config = [
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      // Pixel parity: the fonts load from the same Google Fonts stylesheet as the
      // original static pages instead of next/font (which renames the families).
      '@next/next/no-page-custom-font': 'off',
      // Cross-root-layout navigation is a full page load anyway; plain anchors
      // keep the markup identical to the original pages.
      '@next/next/no-html-link-for-pages': 'off',
      // The original pages use plain <img>; next/image wraps it differently.
      '@next/next/no-img-element': 'off',
    },
  },
  { ignores: ['.next/**', 'node_modules/**', 'next-env.d.ts', 'scripts/**'] },
];

export default config;
