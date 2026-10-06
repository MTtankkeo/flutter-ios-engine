# Flutter iOS engine

공식 Flutter stable 또는 beta에 iOS 입력/화면 표시 지연 패치를 적용해서 빌드하는 저장소입니다. 기존 Flutter fork는 기여용으로 깨끗하게 유지합니다.

## 엔진 만들기

1. **Actions → Build and release iOS engine → Run workflow**에서 `channel`을 **stable / beta** 중 선택하고 `flutter_version`에 정확한 버전을 입력합니다.
2. 빌드와 샘플 앱 빌드가 성공하면 **Releases**에 엔진이 올라옵니다.
3. 기본 버전은 **Flutter 3.47.6**, 패치 버전은 **1**입니다.

stable 버전은 `3.47.6`처럼, beta 버전은 `3.50.0-0.1.pre`처럼 전체 버전을 입력합니다. beta 예시는 입력 형식이며 해당 버전의 패치 호환성을 보장하지 않습니다. 선택한 버전의 공식 tag/채널을 확인하고 실제 커밋을 기록합니다. 다른 버전에 패치가 맞지 않으면 컴파일 전에 중단되므로 패치를 먼저 backport해야 합니다. 현재 패치는 **3.47.6에서 적용 검증**되었습니다.

`build-config.json` 또는 `patches/`를 수정해 `main`에 push하면 기본 설정으로 자동 빌드합니다. 기본 채널·버전과 선택적 고정 커밋은 `build-config.json`에 있습니다. 같은 릴리스 이름은 덮어쓰지 않으므로 동일 Flutter 버전으로 수정된 패치를 배포할 때는 `patch_version`을 올립니다. 수동 버전 선택은 기본 설정 파일을 변경하지 않습니다.

## 앱 CI에서 사용하기

Apple Silicon macOS runner (`macos-15`)와 엔진에 맞는 공식 Flutter SDK를 사용합니다. 아래는 기본 **3.47.6** 릴리스의 사용 예시입니다.

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
- 자동 검증: 선택한 채널/버전/커밋 확인 → patch 적용 → iOS/host 컴파일 → 배포할 파일로 unsigned iOS 앱 빌드.
- 실제 지연 개선과 화면 동작은 실기기에서 별도로 확인해야 합니다.

로컬 빌드: Apple Silicon Mac + Xcode + depot_tools를 준비하고 `python3 scripts/engine.py prepare`, `build`, `package`, `smoke`를 차례로 실행합니다. 새 작업 폴더에서 실행해야 합니다.

로컬에서 다른 버전을 선택하려면 `prepare` 실행 시 `FLUTTER_CHANNEL`과 `FLUTTER_VERSION` 환경변수를 설정합니다. 준비 단계에서 선택을 `.work/build-selection.json`에 저장하며 이후 빌드·패키징·검증·Release 이름은 이 동일한 선택을 사용합니다.

Python 구성: `engine.py`는 명령 진입점, `engine_common.py`는 설정과 경로, `engine_source.py`는 소스 준비, `engine_build.py`는 컴파일, `engine_package.py`는 배포 파일과 샘플 앱 검증을 담당합니다. 테스트는 `python3 -m unittest discover -s scripts -p 'test_*.py'`로 실행합니다.

컴파일 결과는 샘플 앱 검증 전에 Actions artifact로 보존됩니다. 검증이 실패해도 이 artifact를 내려받을 수 있습니다. GitHub Release는 검증까지 성공한 경우에만 게시합니다. 패키징 시 중간 object 파일을 제거하므로 같은 작업 폴더에서 엔진을 다시 빌드하려면 재컴파일이 필요합니다.

공식 참고: [엔진 환경 설정](https://github.com/flutter/flutter/blob/master/docs/engine/contributing/Setting-up-the-Engine-development-environment.md), [엔진 빌드](https://github.com/flutter/flutter/blob/master/docs/engine/contributing/Compiling-the-engine.md).

패치의 Flutter 코드는 원본 BSD 라이선스를 따릅니다. 원본 라이선스는 배포 파일에도 포함됩니다.
