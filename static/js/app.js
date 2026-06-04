/* PageTurner client-side glue.
   Everything submits to the Django backend via fetch + CSRF token. */

(function () {
  "use strict";

  // ----- CSRF token helper ------------------------------------------------
  function getCookie(name) {
    const v = `; ${document.cookie}`;
    const parts = v.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(";").shift();
    return "";
  }
  const csrftoken = getCookie("csrftoken");

  function postJSON(url, data) {
    return fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrftoken,
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify(data || {}),
      credentials: "same-origin",
    }).then(async (r) => {
      let payload = {};
      try { payload = await r.json(); } catch (_) {}
      return { ok: r.ok, status: r.status, data: payload };
    });
  }

  function postForm(url, formData) {
    return fetch(url, {
      method: "POST",
      headers: { "X-CSRFToken": csrftoken, "X-Requested-With": "XMLHttpRequest" },
      body: formData,
      credentials: "same-origin",
    }).then(async (r) => {
      let payload = {};
      try { payload = await r.json(); } catch (_) {}
      return { ok: r.ok, status: r.status, data: payload };
    });
  }

  // ----- Toast ------------------------------------------------------------
  function showToast(msg, kind) {
    const t = document.getElementById("toast");
    if (!t) { console.log(msg); return; }
    document.getElementById("toastMsg").textContent = msg;
    t.classList.add("show");
    const icon = t.querySelector("i");
    if (icon) {
      icon.className = kind === "error" ? "ti ti-alert-circle" : "ti ti-check";
    }
    clearTimeout(t._timer);
    t._timer = setTimeout(() => t.classList.remove("show"), 2600);
  }
  window.showToast = showToast;

  // ----- Star rendering --------------------------------------------------
  function renderStars(rating, size) {
    size = size || 12;
    const full = Math.floor(rating);
    const half = rating % 1 >= 0.5 ? 1 : 0;
    const empty = 5 - full - half;
    let html = "";
    for (let i = 0; i < full; i++) html += `<i class="ti ti-star-filled star-icon" style="font-size:${size}px"></i>`;
    if (half) html += `<i class="ti ti-star-half-filled star-icon" style="font-size:${size}px"></i>`;
    for (let i = 0; i < empty; i++) html += `<i class="ti ti-star star-icon empty" style="font-size:${size}px"></i>`;
    return html;
  }
  window.renderStars = renderStars;

  // ----- Book modal -------------------------------------------------------
  let currentBookId = null;
  let userRating = 0;
  let selectedShelf = "";

  function escapeHtml(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function authorInitials(name) {
    const parts = (name || "").trim().split(/\s+/).filter(Boolean);
    if (parts.length >= 2) return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return "?";
  }

  window.openAuthor = function (name) {
    const modal = document.getElementById("authorModal");
    if (!modal) return;
    document.getElementById("authorModalName").textContent = name;
    document.getElementById("authorModalBio").textContent = "Loading…";
    document.getElementById("authorModalPhoto").innerHTML = "";
    document.getElementById("authorModalStats").textContent = "";
    document.getElementById("authorModalBooks").innerHTML = "";
    modal.style.display = "flex";

    fetch(`/api/author/${encodeURIComponent(name)}/`, { credentials: "same-origin" })
      .then((r) => r.json())
      .then(({ ok, author, books_in_catalog }) => {
        if (!ok) return;
        document.getElementById("authorModalName").textContent = author.name || name;
        const lg = document.getElementById("authorModalNameLg");
        if (lg) lg.textContent = author.name || name;

        const photoEl = document.getElementById("authorModalPhoto");
        if (author.photo_url) {
          photoEl.innerHTML = `<img src="${escapeHtml(author.photo_url)}" alt="${escapeHtml(author.name)}">`;
        } else {
          photoEl.innerHTML = `<div class="author-photo-fallback">${escapeHtml((author.name || "?").charAt(0).toUpperCase())}</div>`;
        }

        const stats = [];
        if (author.birth_date) stats.push(`Born ${escapeHtml(author.birth_date)}`);
        if (author.work_count) stats.push(`${author.work_count.toLocaleString()} works`);
        document.getElementById("authorModalStats").textContent = stats.join(" · ");

        document.getElementById("authorModalBio").textContent =
          author.bio || "No biography available from Open Library yet.";

        const booksEl = document.getElementById("authorModalBooks");
        if (books_in_catalog && books_in_catalog.length) {
          booksEl.innerHTML = `<div class="bk-section-head" style="margin:18px 0 10px">In our catalog</div>` +
            `<div style="display:flex;gap:10px;overflow-x:auto;padding-bottom:4px">` +
            books_in_catalog.map((mb) => `
              <div onclick="closeAuthorModal();openBook(${mb.id})" style="cursor:pointer;flex:0 0 90px">
                <div style="height:130px;background:${escapeHtml(mb.cover_bg)};color:${escapeHtml(mb.cover_color)};border-radius:6px;display:flex;align-items:center;justify-content:center;padding:6px;font-size:11px;text-align:center;overflow:hidden">
                  ${mb.cover_url ? `<img src="${escapeHtml(mb.cover_url)}" alt="${escapeHtml(mb.title)}" style="width:100%;height:100%;object-fit:cover;border-radius:inherit">` : escapeHtml(mb.title.slice(0, 40))}
                </div>
                <div style="font-size:11px;margin-top:4px;color:var(--color-text-primary);line-height:1.3">${escapeHtml(mb.title.slice(0, 30))}</div>
              </div>`).join("") + `</div>`;
        }
      })
      .catch((e) => {
        console.error(e);
        document.getElementById("authorModalBio").textContent = "Couldn't load author info.";
      });
  };
  window.closeAuthorModal = function () {
    const m = document.getElementById("authorModal");
    if (m) m.style.display = "none";
  };

  function openBook(id) {
    fetch(`/api/book/${id}/`, { credentials: "same-origin" })
      .then((r) => r.json())
      .then((b) => {
        currentBookId = b.id;
        userRating = b.user_rating || 0;
        selectedShelf = "";

        // Header text
        document.getElementById("modalTitle").textContent = b.title;
        document.getElementById("modalBookTitle").textContent = b.title;
        const authorEl = document.getElementById("modalBookAuthor");
        authorEl.innerHTML = `by <a href="javascript:void(0)" onclick="openAuthor('${escapeHtml(b.author).replace(/'/g, "\\'")}')" class="author-link">${escapeHtml(b.author)}</a>`;

        // Cover: prefer image, fall back to coloured tile with title
        const cover = document.getElementById("modalCover");
        cover.innerHTML = "";
        if (b.cover_url) {
          const img = document.createElement("img");
          img.src = b.cover_url;
          img.alt = b.title;
          img.style.cssText = "width:100%;height:100%;object-fit:cover;border-radius:inherit";
          cover.style.background = "transparent";
          cover.appendChild(img);
        } else {
          cover.style.background = b.cover_bg;
          cover.style.color = b.cover_color;
          cover.textContent = b.title;
        }

        // Rating row
        document.getElementById("modalStars").innerHTML = renderStars(b.avg_rating, 18);
        document.getElementById("modalRatingNum").textContent = (b.avg_rating || 0).toFixed(2);
        const ratingMeta = b.rated_count
          ? `${b.rated_count.toLocaleString()} rating${b.rated_count === 1 ? "" : "s"} · ${b.review_count.toLocaleString()} review${b.review_count === 1 ? "" : "s"}`
          : "No ratings yet";
        document.getElementById("modalRatingMeta").textContent = ratingMeta;

        // Genres
        const genresEl = document.getElementById("modalGenres");
        const genres = [];
        if (b.genre) genres.push(b.genre);
        if (b.year) genres.push(String(b.year));
        if (b.pages) genres.push(b.pages + " pages");
        genresEl.innerHTML = genres.map((g) => `<span class="genre-pill">${escapeHtml(g)}</span>`).join("");

        // Description with show more
        const descEl = document.getElementById("modalDesc");
        const desc = (b.description || "No description available.").trim();
        descEl.textContent = desc;
        const showMoreBtn = document.getElementById("modalShowMore");
        if (desc.length > 280) {
          descEl.classList.add("is-collapsed");
          showMoreBtn.style.display = "inline-flex";
          showMoreBtn.innerHTML = 'Show more <i class="ti ti-chevron-down"></i>';
        } else {
          descEl.classList.remove("is-collapsed");
          showMoreBtn.style.display = "none";
        }

        // Shelf stats
        const sc = b.shelf_counts || {};
        const statsEl = document.getElementById("modalShelfStats");
        const total = (sc.reading || 0) + (sc.read || 0) + (sc.want || 0) + (sc.favorites || 0);
        if (total) {
          const parts = [];
          if (sc.read) parts.push(`<span><i class="ti ti-check"></i> ${sc.read} read</span>`);
          if (sc.reading) parts.push(`<span><i class="ti ti-book-open"></i> ${sc.reading} reading</span>`);
          if (sc.want) parts.push(`<span><i class="ti ti-bookmark"></i> ${sc.want} want to read</span>`);
          if (sc.favorites) parts.push(`<span><i class="ti ti-heart"></i> ${sc.favorites} favorited</span>`);
          statsEl.innerHTML = parts.join("");
        } else {
          statsEl.innerHTML = "";
        }

        // Want-to-read quick button — active state
        const wantBtn = document.getElementById("modalQuickWant");
        if (b.user_shelf === "want") {
          wantBtn.classList.add("active");
          wantBtn.querySelector("span").textContent = "On Want to Read";
        } else {
          wantBtn.classList.remove("active");
          wantBtn.querySelector("span").textContent = "Want to Read";
        }

        // My-review section: shelf badges, star input, review text
        const shelfMap = {reading: "Reading", read: "Read", want: "Want to Read", favorites: "Favorites"};
        document.querySelectorAll(".shelf-badge").forEach((badge) => {
          badge.classList.remove("active");
          if (shelfMap[b.user_shelf] && badge.dataset.shelf === shelfMap[b.user_shelf]) {
            badge.classList.add("active");
            selectedShelf = shelfMap[b.user_shelf];
          }
        });
        const sr = document.getElementById("modalStarRating");
        sr.innerHTML = [1, 2, 3, 4, 5]
          .map((n) => `<button type="button" class="star-btn" data-n="${n}" onclick="setRating(${n})" onmouseenter="previewRating(${n})" onmouseleave="previewRating(0)" aria-label="${n} stars"><i class="ti ti-star"></i></button>`)
          .join("") + `<span class="rating-label" id="ratingLabel"></span>`;
        updateStarUI(userRating);
        document.getElementById("reviewText").value = b.user_review || "";

        // About the author
        const authorSec = document.getElementById("modalAuthorSection");
        document.getElementById("modalAuthorName").textContent = b.author;
        const authorBooks = b.author_book_count || 1;
        document.getElementById("modalAuthorStat").textContent =
          `${authorBooks} book${authorBooks === 1 ? "" : "s"} in PageTurner`;
        const authorAvatar = document.getElementById("modalAuthorAvatar");
        authorAvatar.textContent = authorInitials(b.author);
        // Deterministic colour based on author name
        const h = Array.from(b.author || "?").reduce((a, c) => a + c.charCodeAt(0), 0);
        const hue1 = h % 360;
        const hue2 = (hue1 + 40) % 360;
        authorAvatar.style.background = `linear-gradient(135deg, hsl(${hue1},45%,55%), hsl(${hue2},45%,45%))`;
        // More by author
        const authorBooksEl = document.getElementById("modalAuthorBooks");
        if (b.more_by_author && b.more_by_author.length) {
          authorBooksEl.innerHTML = b.more_by_author.map((mb) => `
            <div class="bk-mini-book" onclick="openBook(${mb.id})">
              <div class="bk-mini-cover" style="background:${mb.cover_bg};color:${mb.cover_color}">
                ${mb.cover_url
                  ? `<img src="${escapeHtml(mb.cover_url)}" alt="${escapeHtml(mb.title)}" style="width:100%;height:100%;object-fit:cover;border-radius:inherit">`
                  : escapeHtml(mb.title.slice(0, 40))}
              </div>
              <div class="bk-mini-title">${escapeHtml(mb.title.slice(0, 32))}</div>
            </div>
          `).join("");
          authorBooksEl.style.display = "flex";
        } else {
          authorBooksEl.style.display = "none";
        }
        authorSec.style.display = "block";

        // Community Reviews: breakdown + list
        document.getElementById("modalBdAvg").textContent = (b.avg_rating || 0).toFixed(2);
        document.getElementById("modalBdStars").innerHTML = renderStars(b.avg_rating, 16);
        document.getElementById("modalBdCount").textContent =
          `${(b.rated_count || 0).toLocaleString()} rating${b.rated_count === 1 ? "" : "s"} · ${(b.review_count || 0).toLocaleString()} review${b.review_count === 1 ? "" : "s"}`;

        const bd = b.rating_breakdown || {};
        const bdTotal = (bd[5] || 0) + (bd[4] || 0) + (bd[3] || 0) + (bd[2] || 0) + (bd[1] || 0);
        const barsHtml = [5, 4, 3, 2, 1].map((star) => {
          const count = bd[star] || 0;
          const pct = bdTotal ? Math.round((count / bdTotal) * 100) : 0;
          return `
            <div class="bk-bd-row">
              <div class="bk-bd-label">${star} <i class="ti ti-star-filled"></i></div>
              <div class="bk-bd-bar"><div class="bk-bd-bar-fill" style="width:${pct}%"></div></div>
              <div class="bk-bd-pct">${pct}%</div>
            </div>
          `;
        }).join("");
        document.getElementById("modalBdBars").innerHTML = barsHtml;

        const reviewsList = document.getElementById("modalReviewsList");
        if (b.reviews && b.reviews.length) {
          reviewsList.innerHTML = b.reviews.map((r) => `
            <div class="bk-review-item">
              <div class="bk-review-avatar" style="background:linear-gradient(135deg,${escapeHtml(r.avatar_a)},${escapeHtml(r.avatar_b)})">${escapeHtml(r.initials)}</div>
              <div class="bk-review-content">
                <div class="bk-review-head">
                  <a class="bk-review-name" href="/profile/${escapeHtml(r.username)}/">${escapeHtml(r.display_name)}</a>
                  <span class="bk-review-date">${escapeHtml(r.updated_at)}</span>
                </div>
                ${r.rating ? `<div class="bk-review-stars">${renderStars(r.rating, 13)}</div>` : ""}
                ${r.review ? `<div class="bk-review-text">${escapeHtml(r.review)}</div>` : ""}
              </div>
            </div>
          `).join("");
        } else {
          reviewsList.innerHTML = '<p class="bk-empty">Be the first to review this book.</p>';
        }

        // Show modal, scrolled to top
        const modalEl = document.getElementById("bookModal");
        modalEl.style.display = "flex";
        const inner = modalEl.querySelector(".modal");
        if (inner) inner.scrollTop = 0;
      })
      .catch((e) => {
        console.error(e);
        showToast("Couldn't load that book.");
      });
  }
  window.openBook = openBook;

  // Quick shelf action from the cover area (Want to Read / On Want to Read)
  window.quickShelf = function (shelfKey) {
    if (!currentBookId) return;
    const labelMap = {reading: "Reading", read: "Read", want: "Want to Read", favorites: "Favorites"};
    const label = labelMap[shelfKey] || "Want to Read";
    postJSON(`/api/book/${currentBookId}/save/`, {shelf: label}).then(({ ok, data }) => {
      showToast((data && data.message) || (ok ? "Saved." : "Couldn't save."));
      if (ok) {
        // Reload modal to refresh stats
        openBook(currentBookId);
      }
    });
  };

  // Show more / Show less for the description
  window.toggleDesc = function () {
    const d = document.getElementById("modalDesc");
    const btn = document.getElementById("modalShowMore");
    if (d.classList.contains("is-collapsed")) {
      d.classList.remove("is-collapsed");
      btn.innerHTML = 'Show less <i class="ti ti-chevron-up"></i>';
    } else {
      d.classList.add("is-collapsed");
      btn.innerHTML = 'Show more <i class="ti ti-chevron-down"></i>';
    }
  };

  function closeModal(e) {
    if (!e || e.target.id === "bookModal") {
      document.getElementById("bookModal").style.display = "none";
    }
  }
  window.closeModal = closeModal;

  function updateStarUI(n) {
    document.querySelectorAll("#modalStarRating .star-btn").forEach((s, i) => {
      const lit = i < n;
      const ic = s.querySelector("i");
      if (ic) ic.className = `ti ${lit ? "ti-star-filled" : "ti-star"}`;
      s.classList.toggle("lit", lit);
    });
    const lbl = document.getElementById("ratingLabel");
    if (lbl) lbl.textContent = n ? `${n} / 5` : "Click a star to rate";
  }

  window.setRating = function (n) {
    userRating = n;
    updateStarUI(n);
  };
  window.previewRating = function (n) {
    updateStarUI(n || userRating);
  };

  function saveBook() {
    if (!currentBookId) return;
    const review = document.getElementById("reviewText").value.trim();
    postJSON(`/api/book/${currentBookId}/save/`, {
      shelf: selectedShelf,
      rating: userRating,
      review,
    }).then(({ ok, data }) => {
      if (ok && data.ok) {
        showToast(data.message || "Saved.");
        closeModal();
        // Refresh page if we're on shelves/feed so it reflects the change
        if (/shelves|feed|home|profile/.test(window.location.pathname) || window.location.pathname === "/") {
          setTimeout(() => window.location.reload(), 800);
        }
      } else {
        showToast(data.error || "Couldn't save. Pick a shelf or add a rating.", "error");
      }
    });
  }
  window.saveBook = saveBook;

  // ----- Modal interactions (delegated) -----------------------------------
  document.addEventListener("click", (e) => {
    // Shelf badge
    const badge = e.target.closest(".shelf-badge");
    if (badge) {
      document.querySelectorAll(".shelf-badge").forEach((b) => b.classList.remove("active"));
      badge.classList.add("active");
      selectedShelf = badge.dataset.shelf;
    }
  });

  // ----- Like (visual only — no backend persistence on this MVP) ---------
  window.likePost = function (btn) {
    btn.classList.toggle("liked");
    const span = btn.querySelector("span");
    if (span) span.textContent = btn.classList.contains("liked") ? "Liked" : "Like";
  };

  // ----- Notifications ----------------------------------------------------
  window.markNotifRead = function (el, id) {
    if (!el.classList.contains("unread")) return;
    postJSON(`/api/notification/${id}/read/`, {}).then(({ ok }) => {
      if (!ok) return;
      el.classList.remove("unread");
      const remaining = document.querySelectorAll(".notif.unread").length;
      const sub = document.getElementById("notif-sub");
      if (sub) {
        sub.textContent = remaining
          ? `You have ${remaining} unread notification${remaining > 1 ? "s" : ""}.`
          : "All caught up!";
      }
      const badge = document.querySelector("#sb-notifications .badge");
      if (badge) {
        if (remaining) badge.textContent = remaining;
        else badge.remove();
      }
    });
  };

  // ----- Challenge goal slider ------------------------------------------
  let goalTimer = null;
  window.updateGoal = function (val) {
    const goalDisplay = document.getElementById("goalDisplay");
    if (goalDisplay) goalDisplay.textContent = val + " books";
    // Optimistically update ring
    const read = parseInt(document.getElementById("chRead").textContent, 10) || 0;
    const pct = Math.min(100, Math.round((read / val) * 100));
    const ring = document.getElementById("challengeRing");
    if (ring) {
      const c = 263.9;
      ring.style.strokeDashoffset = c * (1 - pct / 100);
    }
    document.getElementById("chGoal").textContent = "of " + val;
    document.getElementById("chPct").textContent = pct + "%";
    document.getElementById("chLeft").textContent = Math.max(0, val - read);
    // Debounced persist
    clearTimeout(goalTimer);
    goalTimer = setTimeout(() => {
      const fd = new FormData();
      fd.append("goal", val);
      postForm("/api/challenge/goal/", fd).then(({ ok }) => {
        if (ok) showToast("Goal updated.");
      });
    }, 500);
  };

  // ----- Friends: request / accept / decline / unfriend ------------------
  window.addFriend = function (btn, userId) {
    postJSON(`/api/user/${userId}/friend-request/`, {}).then(({ ok, data, status }) => {
      if (!ok) {
        showToast((data && data.error) || "Could not send request.");
        return;
      }
      if (data.status === "friends" || data.status === "already_friends") {
        btn.classList.add("following");
        btn.textContent = "Friends";
        btn.onclick = () => unfriendUser(btn, userId);
        showToast("You're now friends.");
      } else if (data.status === "pending" || data.status === "already_pending") {
        btn.classList.add("following");
        btn.textContent = "Request sent";
        btn.disabled = true;
      }
    });
  };

  window.unfriendUser = function (btn, userId) {
    if (!confirm("Remove this friend?")) return;
    postJSON(`/api/user/${userId}/unfriend/`, {}).then(({ ok }) => {
      if (!ok) return;
      btn.classList.remove("following");
      btn.disabled = false;
      btn.textContent = "Add friend";
      btn.onclick = () => addFriend(btn, userId);
      showToast("Friend removed.");
    });
  };

  window.respondRequest = function (reqId, decision) {
    const fd = new FormData();
    fd.append("decision", decision);
    postForm(`/api/friend-request/${reqId}/respond/`, fd).then(({ ok, data }) => {
      if (!ok) return;
      const card = document.getElementById(`req-${reqId}`);
      if (card) card.remove();
      showToast(decision === "accept" ? "You're now friends." : "Request declined.");
      if (decision === "accept") setTimeout(() => window.location.reload(), 600);
    });
  };

  // Legacy alias — older templates may still call toggleFollow.
  window.toggleFollow = function (btn, userId) { return addFriend(btn, userId); };

  // ----- Import a remote search result (Google Books / Open Library) -----
  window.importAndOpen = function (volumeId, source) {
    showToast("Loading book…");
    postJSON("/api/book/import/", { volume_id: volumeId, source: source || "" }).then(({ ok, data }) => {
      if (!ok || !data || !data.book) {
        showToast((data && data.error) || "Could not load that book.");
        return;
      }
      openBook(data.book.id);
    });
  };

  // ----- Report content --------------------------------------------------
  window.reportContent = function (targetType, targetId) {
    const reason = prompt("Reason (spam / harassment / inappropriate / fake / other):", "spam");
    if (!reason) return;
    const detail = prompt("Optional details:", "") || "";
    postJSON("/api/report/", { target_type: targetType, target_id: targetId, reason, detail })
      .then(({ ok, data }) => {
        showToast((data && data.message) || (ok ? "Reported." : "Could not report."));
      });
  };

  // ----- Search: enter to submit -----------------------------------------
  const searchInput = document.getElementById("searchInput");
  if (searchInput) {
    searchInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        const q = searchInput.value.trim();
        window.location.href = "/discover/" + (q ? "?q=" + encodeURIComponent(q) : "");
      }
    });
  }

  // ----- Close modal on Escape -------------------------------------------
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") closeModal();
  });

  // ----- Buddy Reads -----------------------------------------------------
  window.openBuddyInvite = function () {
    const panel = document.getElementById("buddyInvitePanel");
    const list = document.getElementById("buddyFriendList");
    if (!panel || !currentBookId) return;
    if (panel.style.display === "block") { panel.style.display = "none"; return; }
    panel.style.display = "block";
    list.innerHTML = "Loading friends…";
    fetch(`/api/buddy/candidates/${currentBookId}/`, { credentials: "same-origin" })
      .then((r) => r.json())
      .then(({ ok, friends }) => {
        if (!ok) return;
        if (!friends.length) {
          list.innerHTML = `<span style="font-size:13px;color:var(--color-text-secondary)">No friends available. Add friends first, or they already have a buddy read for this book with you.</span>`;
          return;
        }
        list.innerHTML = friends.map((f) => `
          <button class="buddy-friend-row" onclick="sendBuddyInvite(${f.id}, this)">
            <span class="user-avatar" style="background:linear-gradient(135deg,${f.avatar_a},${f.avatar_b})">${escapeHtml(f.initials)}</span>
            <span>${escapeHtml(f.name)}</span>
            <span class="buddy-friend-cta"><i class="ti ti-send"></i> Invite</span>
          </button>`).join("");
      });
  };

  window.sendBuddyInvite = function (partnerId, btn) {
    if (!currentBookId) return;
    btn.disabled = true;
    postJSON("/api/buddy/invite/", { book_id: currentBookId, partner_id: partnerId })
      .then(({ ok, data }) => {
        if (ok && data.ok) {
          btn.innerHTML = `<span class="user-avatar" style="background:var(--pt-gold)"><i class="ti ti-check"></i></span><span>Invited!</span>`;
          showToast("Buddy read invite sent.");
        } else {
          btn.disabled = false;
          showToast((data && data.error) || "Could not send invite.");
        }
      });
  };

  window.buddyRespond = function (brId, decision) {
    const fd = new FormData();
    fd.append("decision", decision);
    postForm(`/api/buddy/${brId}/respond/`, fd).then(({ ok, data }) => {
      if (!ok) return;
      const card = document.getElementById(`br-${brId}`);
      if (card) card.remove();
      showToast(decision === "accept" ? "Buddy read started!" : "Invite declined.");
      if (decision === "accept") setTimeout(() => window.location.reload(), 700);
    });
  };

  // ----- Reading streak heatmap (profile page) ---------------------------
  function renderHeatmap() {
    const el = document.getElementById("heatmap");
    if (!el) return;
    const username = el.dataset.user || "";
    fetch(`/api/streak/?user=${encodeURIComponent(username)}`, { credentials: "same-origin" })
      .then((r) => r.json())
      .then(({ ok, days, current_streak }) => {
        if (!ok) return;
        const streakVal = document.getElementById("streakVal");
        if (streakVal) streakVal.textContent = current_streak;

        // Group days into weeks (columns of 7), like GitHub.
        const max = Math.max(1, ...days.map((d) => d.count));
        const level = (c) => {
          if (!c) return 0;
          const r = c / max;
          if (r > 0.66) return 4;
          if (r > 0.33) return 3;
          if (r > 0.1) return 2;
          return 1;
        };
        let html = '<div class="hm-grid">';
        for (let i = 0; i < days.length; i += 7) {
          html += '<div class="hm-col">';
          for (let j = i; j < i + 7 && j < days.length; j++) {
            const d = days[j];
            html += `<span class="hm-cell lvl${level(d.count)}" title="${d.date}: ${d.count} action${d.count === 1 ? "" : "s"}"></span>`;
          }
          html += "</div>";
        }
        html += "</div>";
        el.innerHTML = html;
      })
      .catch(() => {
        el.innerHTML = '<span style="color:var(--color-text-secondary);font-size:13px">Couldn\'t load activity.</span>';
      });
  }
  document.addEventListener("DOMContentLoaded", renderHeatmap);
  if (document.readyState !== "loading") renderHeatmap();
})();
