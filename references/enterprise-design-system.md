# Enterprise diagram design system

- Canvas: 16:9 widescreen for PowerPoint; light neutral background.
- Primary: navy `#183153`; blue `#3069A4`; teal `#198282`; neutral text `#34495E`.
- Use pale fills for component families; reserve amber for inferred and red for unknown/unverified details.
- Shapes: rounded rectangles for applications and services, cylinders for databases, rounded pills for people.
- Layout: left to right along the arrows, laid out automatically by the generator.
- Arrows: solid for direct requests and data access, dashed for messages, events, files, and scheduled jobs. Each arrow carries its step number and a short label.
- Keep labels concise; move detailed descriptions to notes/documentation.
- Provide a legend and avoid relying on color alone: also mark inferred/unknown items with text.
- Keep each view to 8 elements or fewer. Split larger systems into multiple views.
- Never add vendor logos or cloud-service icons unless the source identifies the product/provider.
