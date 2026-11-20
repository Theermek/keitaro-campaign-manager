// Alpine.js components. Loaded before Alpine itself (both deferred, order preserved).

async function api(method, url, body) {
  const response = await fetch(url, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(errorText(data, response.status));
    error.data = data;
    throw error;
  }
  return data;
}

function errorText(data, status) {
  if (typeof data.error === "string") {
    return data.detail ? `${data.error}: ${data.detail}` : data.error;
  }
  // FastAPI validation errors
  if (Array.isArray(data.detail)) {
    return data.detail.map((d) => `${d.loc.at(-1)}: ${d.msg}`).join("; ");
  }
  return `Request failed (${status})`;
}

function offerPicker() {
  return {
    query: "",
    results: [],
    selected: null,
    open: false,
    loading: false,
    cursor: 0,
    async search() {
      // Typing after a choice invalidates it
      if (this.selected && this.query !== this.selected.name) this.selected = null;
      this.open = true;
      this.loading = true;
      try {
        this.results = await api("GET", `/api/offers?q=${encodeURIComponent(this.query)}`);
      } catch (e) {
        this.results = [];
      } finally {
        this.loading = false;
        this.cursor = 0;
      }
    },
    move(step) {
      if (!this.results.length) return;
      this.cursor = (this.cursor + step + this.results.length) % this.results.length;
    },
    choose(offer) {
      if (!offer) return;
      this.selected = offer;
      this.query = offer.name;
      this.open = false;
    },
    reset() {
      this.selected = null;
      this.query = "";
      this.results = [];
    },
  };
}

const clone = (value) => JSON.parse(JSON.stringify(value));
const shareRow = (o) => ({ offer_id: o.offer_id, share: o.share, pinned: o.pinned, removed: o.removed });

function editorPage() {
  return {
    campaigns: [],
    campaignId: null,
    streams: [],
    otherStreams: [],
    loading: false,
    error: "",

    async init() {
      const id = Number(new URLSearchParams(location.search).get("campaign"));
      try {
        this.campaigns = await api("GET", "/api/campaigns");
      } catch (e) {
        this.error = e.message;
        return;
      }
      if (id) {
        this.campaignId = id;
        await this.fetchStreams();
      }
    },

    selectCampaign() {
      const url = new URL(location.href);
      if (this.campaignId) url.searchParams.set("campaign", this.campaignId);
      else url.searchParams.delete("campaign");
      history.replaceState(null, "", url);
      this.streams = [];
      this.otherStreams = [];
      if (this.campaignId) this.fetchStreams();
    },

    // Reloads from Keitaro; unpublished drafts are dropped
    async fetchStreams() {
      this.loading = true;
      this.error = "";
      try {
        const data = await api("GET", `/api/campaigns/${this.campaignId}/streams`);
        this.streams = data.streams.map((s) => this.wrap(s));
        this.otherStreams = data.other_streams;
      } catch (e) {
        this.error = e.message;
        this.streams = [];
        this.otherStreams = [];
      } finally {
        this.loading = false;
      }
    },

    wrap(stream) {
      // `original` is what Keitaro has; `draft` is edited until Push or Cancel. Both in Keitaro order.
      return { ...stream, original: clone(stream.offers), draft: clone(stream.offers), newOffer: null, busy: false, error: "" };
    },

    dirty(s) {
      const key = (rows) => JSON.stringify(rows.map((o) => [o.offer_id, o.share, o.removed]));
      return key(s.draft) !== key(s.original);
    },

    activeCount(s) {
      return s.draft.filter((o) => !o.removed).length;
    },

    total(s) {
      return s.draft.filter((o) => !o.removed).reduce((sum, o) => sum + o.share, 0);
    },

    // Display order: share descending (ties keep Keitaro order), removed at the bottom
    sorted(s) {
      return s.draft
        .map((o, i) => ({ o, i }))
        .sort((a, b) => a.o.removed - b.o.removed || b.o.share - a.o.share || a.i - b.i)
        .map(({ o }) => o);
    },

    async rebalance(s) {
      s.error = "";
      try {
        const rows = await api("POST", "/api/shares/rebalance", { offers: s.draft.map(shareRow) });
        rows.forEach((r, i) => { s.draft[i].share = r.share; });
      } catch (e) {
        s.error = e.message;
      }
    },

    async add(s) {
      const offer = s.newOffer;
      if (!offer) return;
      const existing = s.draft.find((o) => o.offer_id === offer.id);
      if (existing && !existing.removed) {
        s.error = `Offer ${offer.id} is already in this stream`;
        return;
      }
      if (existing) {
        existing.removed = false;
      } else {
        s.draft.push({ offer_id: offer.id, name: offer.name, share: 0, pinned: false, removed: false });
      }
      s.newOffer = null;
      window.dispatchEvent(new CustomEvent("offer-added", { detail: s.id }));
      await this.rebalance(s);
    },

    async remove(s, row) {
      const published = s.original.some((o) => o.offer_id === row.offer_id);
      if (published) {
        row.removed = true;
        row.pinned = false;
      } else {
        // Added in this draft only: just drop it
        s.draft.splice(s.draft.indexOf(row), 1);
      }
      await this.rebalance(s);
    },

    async bringBack(s, row) {
      row.removed = false;
      await this.rebalance(s);
    },

    // Pins of published offers are saved at once; pins of new offers go with Push
    async togglePin(s, row) {
      const pinned = !row.pinned;
      const saved = s.original.find((o) => o.offer_id === row.offer_id && !o.removed);
      if (saved) {
        try {
          await api("PATCH", `/api/streams/${s.id}/offers/${row.offer_id}`, { pinned });
          saved.pinned = pinned;
        } catch (e) {
          s.error = e.message;
          return;
        }
      }
      row.pinned = pinned;
    },

    cancel(s) {
      s.draft = clone(s.original);
      s.error = "";
    },

    async push(s) {
      s.busy = true;
      s.error = "";
      try {
        const result = await api("PUT", `/api/streams/${s.id}/offers`, {
          base: s.original.filter((o) => !o.removed).map((o) => ({ offer_id: o.offer_id, share: o.share })),
          offers: s.draft.map((o) => ({ ...shareRow(o), name: o.name })),
        });
        Object.assign(s, this.wrap(result));
      } catch (e) {
        s.error = e.message;
      } finally {
        s.busy = false;
      }
    },
  };
}

function createForm(prefix) {
  return {
    suffix: "",
    geo: "",
    offer: null,
    busy: false,
    error: "",
    created: null,
    valid() {
      return this.suffix.length > 0 && /^[A-Z]{2}$/.test(this.geo) && this.offer !== null;
    },
    async submit() {
      if (!this.valid() || this.busy) return;
      this.busy = true;
      this.error = "";
      this.created = null;
      try {
        this.created = await api("POST", "/api/campaigns", {
          name: prefix + this.suffix,
          geo: this.geo,
          offer_id: this.offer.id,
        });
        this.suffix = "";
      } catch (e) {
        this.error = e.message;
      } finally {
        this.busy = false;
      }
    },
  };
}
