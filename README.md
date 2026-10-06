# Flutter iOS engine

공식 Flutter stable에 iOS 입력/화면 표시 지연 패치만 적용해서 빌드하는 저장소입니다. 기존 Flutter fork는 기여용으로 깨끗하게 유지합니다.

## 엔진 만들기

1. `build-config.json` 또는 `patches/`를 수정하고 `main`에 push하면 자동으로 시작됩니다. 수동 재실행은 **Actions → Build and release iOS engine → Run workflow**를 사용합니다.
2. 빌드와 샘플 앱 빌드가 성공하면 **Releases**에 엔진이 올라옵니다.
3. 기본 버전은 **Flutter 3.47.6**, 패치 버전은 **1**입니다.

버전을 올릴 때는 `build-config.json`의 Flutter 버전/공식 커밋과 패치 버전을 함께 수정합니다. `Check stable patch`가 새 stable에 패치가 적용되는지 확인합니다. 충돌이 있으면 패치를 먼저 고쳐야 합니다. 같은 릴리스 이름은 덮어쓰지 않습니다.

## 앱 CI에서 사용하기

Apple Silicon macOS runner (`macos-15`)와 공식 **Flutter 3.47.6** SDK를 사용합니다. 릴리스 파일을 내려받아 검증하고 압축을 풉니다.

```bash
TAG=flutter-3.47.6-ios-latency.1
mkdir -p custom-engine
cd custom-engine
gh release download "$TAG" --repo MTtankkeo/flutter-ios-engine \
  --pattern '*.tar.gz' --pattern '*.sha256'
shasum -a 256 -c "$TAG.tar.gz.sha256"
tar -xzf "$TAG.tar.gz"
cd ..

flutter --local-engine-src-path="$PWD/custom-engine/engine/src" \
  --local-engine=ios_release \
  --local-engine-host=host_release_arm64 \
  build ipa --release
```

서명 인증서와 provisioning profile은 기존 앱 CI 설정을 사용합니다. 엔진을 만든 Flutter 버전과 앱 SDK 버전은 반드시 일치해야 합니다. iOS 실기기 release 빌드용이며 simulator/debug/profile은 포함하지 않습니다.

## 패치 출처와 확인 범위

- 원본: `MTtankkeo/flutter`의 `da9796bc8b943f37ab9db2a0f5a6e7a7aa82e338` 최종 diff.
- `3.47.6`에 맞춰 충돌을 해결했고 Swift 공개 API를 유지했습니다.
- 별개인 wide-gamut GPU 수정과 해당 테스트는 이 패치에서 제외했습니다.
- 입력 전달, vsync 등록, Darwin autorelease pool, Metal presentation, platform view transaction 관련 최종 변경과 연관 테스트 수정이 포함됩니다.
- 실패한 실험의 중간 커밋은 가져오지 않습니다. 최종 diff에 남아 있는 presentation 구현을 유지합니다.
- 자동 검증: stable 출처/커밋 확인 → patch 적용 → iOS/host 컴파일 → 배포할 파일로 unsigned iOS 앱 빌드.
- 실제 지연 개선과 화면 동작은 실기기에서 별도로 확인해야 합니다.

로컬 빌드: Apple Silicon Mac + Xcode + depot_tools를 준비하고 `python3 scripts/engine.py prepare`, `build`, `package`, `smoke`를 차례로 실행합니다. 새 작업 폴더에서 실행해야 합니다.

컴파일 결과는 샘플 앱 검증 전에 Actions artifact로 보존됩니다. 검증이 실패해도 이 artifact를 내려받을 수 있습니다. GitHub Release는 검증까지 성공한 경우에만 게시합니다. 패키징 시 중간 object 파일을 제거하므로 같은 작업 폴더에서 엔진을 다시 빌드하려면 재컴파일이 필요합니다.

공식 참고: [엔진 환경 설정](https://github.com/flutter/flutter/blob/master/docs/engine/contributing/Setting-up-the-Engine-development-environment.md), [엔진 빌드](https://github.com/flutter/flutter/blob/master/docs/engine/contributing/Compiling-the-engine.md).

패치의 Flutter 코드는 원본 BSD 라이선스를 따릅니다. 원본 라이선스는 배포 파일에도 포함됩니다.
