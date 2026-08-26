# Static Report / Dashboard Template Guide

이 문서는 다른 내부 프로젝트에도 재사용할 수 있는 static Report/Dashboard template의
간단한 사용 가이드입니다. 프로젝트 고유의 내용은 예시로만 남기고, 폴더/컴포넌트
구조를 재사용하는 것을 목표로 합니다.

## Directory layout

```text
artifacts/
├─ index.html
├─ shared/
│  └─ styles.css
├─ assets/images/<project>/
├─ report/
│  ├─ index.html
│  └─ <numbered-pages>.html
└─ dashboard/
   ├─ index.html
   └─ <status-pages>.html
```

`report/`는 프로젝트의 배경, 구조, 흐름, 성과와 future direction을 설명합니다.
`dashboard/`는 현재 capability, evidence freshness, known issues와 backlog를 보여줍니다.
기술 문서와 실행 artifact가 source of truth라면 Pages는 이를 요약하는 presentation
layer로 유지합니다.

## Shared CSS

모든 HTML은 `shared/styles.css` 하나를 참조합니다. 색상 token, layout, card, status pill,
stat tile, table, timeline, flow, screenshot frame과 responsive breakpoint를 이 파일에서
관리합니다. 페이지별 inline CSS는 특별한 이유가 있을 때만 사용합니다.

기본 visual token은 navy primary, gold accent, green good, red critical, orange warning,
muted gray입니다. 색상만으로 상태를 전달하지 말고 텍스트 status와 함께 사용합니다.

## Page structure

각 페이지는 다음 순서를 기본으로 합니다.

1. `lang`, charset, viewport, description, unique title
2. skip link와 semantic header/nav
3. `main` 안의 hero, cards/tables/flow/timeline
4. 페이지 목적에 맞는 footer navigation

키보드 focus는 `:focus-visible`에서 항상 보이게 하고, heading 순서와 link text를
확인합니다. 모바일에서는 grid가 한 열로 바뀌고 table은 가로 스크롤을 허용합니다.

## Images and screenshots

이미지는 `assets/images/<project>/`에 stable filename으로 저장합니다. 각 content image에는
현재 화면의 의미를 설명하는 alt text와 source/date/scope를 설명하는 caption을 붙입니다.
스크린샷이 지표를 증명하지 않는다면 “UI example”임을 명시합니다. 민감정보가 보이면
사용 전 공개 범위를 확인하고, 원본을 조용히 수정하지 않습니다.

## Navigation

동일한 header navigation을 홈, Report, Dashboard, 기술 문서 링크에 사용합니다. Pages에서
Markdown이 렌더링된다고 가정하지 말고, 기술 문서는 repository의 안정적인 HTTPS URL이나
Pages가 실제로 제공하는 HTML URL로 연결합니다. 로컬 filesystem URL과 Windows 경로는
사용하지 않습니다.

## Reusable components

- **Card**: 하나의 capability나 destination을 요약
- **Status pill**: 구현/제한/미구현처럼 짧은 상태 표시
- **Stat tile**: count 또는 상태를 의미와 함께 표시
- **Table**: 반복되는 상태/근거/백로그 비교
- **Timeline / flow**: 실행 순서와 lifecycle 표시
- **Screenshot frame**: image, alt text, caption 묶음
- **Roadmap visual**: current architecture와 future direction의 전환 표시

## Project-specific replacement points

프로젝트별로 다음을 교체합니다.

- 제목, subtitle, brand mark
- Report section titles와 stakeholder language
- Dashboard status taxonomy
- source-of-truth 링크와 evidence scope/date
- image filenames, alt text, captions
- capability, limitation, backlog rows
- roadmap stages와 implementation boundary

현재 capability, historical evidence, known limitation, future roadmap을 하나의 status로
합치지 않습니다. 특히 future concept을 구현 완료처럼 표시하지 않고, historical 숫자는
날짜와 scope를 붙여 표시합니다.
