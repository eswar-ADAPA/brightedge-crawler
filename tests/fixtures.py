"""HTML fixtures used by the unit tests.

Kept inline (not in separate files) so tests are easy to read top-to-bottom.
"""

PRODUCT_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
  <title>Best Toaster Ever — ExampleShop</title>
  <meta name="description" content="Two-slice toaster with 7 shade settings.">
  <meta property="og:title" content="Best Toaster Ever">
  <meta property="og:type" content="product">
  <meta property="og:site_name" content="ExampleShop">
  <link rel="canonical" href="https://example.shop/toaster">
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "Product",
    "name": "Best Toaster Ever",
    "brand": {"@type": "Brand", "name": "CrumbCo"},
    "category": "Kitchen Appliance"
  }
  </script>
</head>
<body>
  <h1>Best Toaster Ever</h1>
  <p>Two slots. Seven settings. Removable crumb tray. Built for bagels and
  bread. Defrost, reheat, cancel buttons. Backed by a one-year warranty.</p>
</body>
</html>
"""

ARTICLE_HTML_WITH_GRAPH = """
<!DOCTYPE html>
<html lang="en">
<head>
  <title>AI Is Eating Software | Example News</title>
  <meta name="description" content="A study finds 90% of developers use AI.">
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "NewsArticle",
        "headline": "AI Is Eating Software",
        "datePublished": "2025-09-23T08:00:00Z",
        "articleSection": ["tech", "business"],
        "keywords": "AI, software, productivity",
        "author": {"@type": "Person", "name": "Jane Doe"}
      },
      {
        "@type": "Organization",
        "name": "Example News"
      }
    ]
  }
  </script>
</head>
<body>
  <h1>AI Is Eating Software</h1>
  <article>
    <p>A new study published this week concludes that the overwhelming
    majority of professional software developers use AI assistants daily,
    for tasks ranging from boilerplate generation to code review and
    debugging across the industry.</p>
  </article>
</body>
</html>
"""

PLAIN_HTML_NO_STRUCTURED = """
<!DOCTYPE html>
<html>
<head><title>Just A Page</title>
<meta name="description" content="Nothing fancy here, just words on a page."></head>
<body><p>One paragraph of body text and not much else to say about it.</p></body>
</html>
"""

ANTI_BOT_STUB_HTML = """
<!DOCTYPE html>
<html>
<head><title>Amazon.com</title></head>
<body><p>Click the button below to continue shopping</p></body>
</html>
"""
