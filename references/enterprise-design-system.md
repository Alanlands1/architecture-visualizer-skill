# Enterprise diagram design system

- Canvas: 16:9 widescreen for PowerPoint; light neutral background.
- Primary: navy `#183153`; blue `#3069A4`; teal `#198282`; neutral text `#34495E`.
- Use pale fills for component families; reserve amber for inferred and red for unknown/unverified details.
- Use rounded rectangles for applications/services, cylinder-like or database-specific shapes where renderer support is reliable, and clear boundaries for trust zones.
- Use orthogonal connectors where possible. Label every important connection with protocol, event, operation, or data type when the source provides it.
- Keep labels concise; move detailed descriptions to notes/documentation.
- Provide a legend and avoid relying on color alone: also mark inferred/unknown items with text.
- Prefer 3–7 elements per view. Split larger systems into multiple views.
- Never add vendor logos or cloud-service icons unless the source identifies the product/provider.
