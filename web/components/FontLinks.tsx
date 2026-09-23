/**
 * The exact Google Fonts stylesheet the original static pages used. Kept
 * instead of next/font so the font-family names in base.css (`'DM Serif
 * Display'`, `'Schibsted Grotesk'`, `'JetBrains Mono'`) resolve unchanged.
 */
export function FontLinks() {
  return (
    <>
      <link rel="preconnect" href="https://fonts.googleapis.com" />
      <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
      <link
        href="https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital,wght@0,400;1,400&family=Schibsted+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap"
        rel="stylesheet"
      />
    </>
  );
}
