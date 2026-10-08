# 智导 KnowledgeHub — reference UI

The seven screenshots supplied on 2026-10-07 define this app's visual direction.
Preserve existing routes, native components, authentication, live data and role gates.
Do not replace working features with flattened screenshot images.

## Shared system

- Genre: restrained enterprise workspace, red/white, warm and soft.
- Login: photographic split layout, white brand/copy, one translucent light form.
- App: existing left navigation, open working canvas, pale coral corner curves.
- Collections: rounded near-white cards, aligned action rows. Scripts and rules use a middle group rail and compact responsive cards (user-requested update, 2026-10-08).
- Typography: existing Chinese UI font; upright Songti display on login only.
- Motion: existing functional feedback only; no animated backgrounds or new scroll reveals.
- Real names, counts, timestamps and permissions remain supplied by the application.
- Dark mode retains its semantic theme; decorative pale backgrounds are suppressed.

## Tokens and components

The reference-specific tokens live in `tokens.css` (`--kh-ui-*`).
The scoped application overrides live in `frontend/src/assets/theme/reference-ui.css`.
Login uses `frontend/src/views/auth/login.css`; its input and validation contracts remain native TDesign.
All secondary controls retain visible keyboard focus and disabled/loading states.
No external image or font CDN is required.

## Brand imagery

`frontend/public/brand/classbro-mark.png` is an AI-cleaned transparent variant of the supplied raster logo.
`frontend/public/brand/study-room.png` is a background reconstructed from the supplied login reference,
not the original photograph. Preserve the supplied original outside this derived asset.

## Responsive policy

Keep user-resizable desktop navigation. On narrow screens the sidebar uses its existing collapsed controls.
Cards wrap into one column, page actions wrap without clipping their labels, login keeps the form first.
The decorative background never receives pointer events or conveys application state.
