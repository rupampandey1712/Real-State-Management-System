import { Component, type ReactNode } from "react";

/** The map is an enhancement (ADR-0018). If its code fails to load or it throws (no WebGL, old device, blocked
 *  tiles), only the map disappears — never the listing or search page around it. */
export default class MapBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  render() {
    if (this.state.failed) {
      return <p className="rounded-lg border border-rule bg-paper p-4 text-sm text-slate" role="status">The map couldn't load on this device. Everything else on the page still works.</p>;
    }
    return this.props.children;
  }
}
