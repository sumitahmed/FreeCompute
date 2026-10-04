import { defineConfig } from 'astro/config';

export default defineConfig({
  output: 'static',
  // Supply the real public site URL when hosting is chosen.
  ...(process.env.SITE_URL ? { site: process.env.SITE_URL } : {}),
  base: process.env.BASE_PATH || '/',
  trailingSlash: 'always',
  devToolbar: { enabled: false },
});
