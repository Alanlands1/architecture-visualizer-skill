# Enterprise diagram design system

- Canvas: 16:9 widescreen for PowerPoint; light neutral background.
- Primary: navy `#183153`; blue `#3069A4`; teal `#198282`; neutral text `#34495E`.
- Use pale fills for component families; reserve amber for inferred and red for unknown/unverified details.
- Shapes: rounded rectangles for applications and services, cylinders for databases and secrets stores, rounded pills for people, hexagons for firewalls, WAFs, and VPNs.
- Zones: dashed frames with the zone name in the top corner, ordered left to right from least trusted to most trusted.
- Layout: left to right along the arrows, laid out automatically by the generator.
- Arrows: solid for direct requests and data access, dashed for messages, events, files, and scheduled jobs. Each arrow carries its step number and a short label. Teal arrows are encrypted and red arrows are blocked; both also say so in words.
- Keep labels concise; move detailed descriptions to notes/documentation.
- Provide a legend and avoid relying on color alone: also mark inferred/unknown items with text.
- Keep each view to 8 elements or fewer. Split larger systems into multiple views.
- Never add vendor logos or cloud-service icons unless the source identifies the product/provider.
