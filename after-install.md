# Open ImageGen

Enable both the ImageGen agent plugin and its Desktop UI in **Capabilities →
Plugins**; Hermes installs the Desktop UI turned off. Restart Hermes once to load the backend routes, then open
**ImageGen** from the sidebar. Provider credentials already configured in
the active Hermes profile are reused. To use FAL without a Nous Portal
subscription, or Magnific, add those keys in **Settings → Plugins →
ImageGen**. Each generation is billed to the provider account that owns the
key.

To let the agent's images use ImageGen too, pick **ImageGen** under
**Capabilities → Tools → Image Generation**. They then land in the ImageGen
gallery and budget.

If only the interface was selected during installation, install the agent
component from the same repository as well. Both parts are required.
