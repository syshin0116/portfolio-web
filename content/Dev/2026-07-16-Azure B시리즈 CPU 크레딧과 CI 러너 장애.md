---
title: Azure B시리즈 CPU 크레딧 고갈로 CI가 무너진 날
date: 2026-07-16
tags:
  - dev
  - azure
  - aks
  - github-actions
  - ci-cd
  - troubleshooting
draft: false
enableToc: true
description: GitHub Actions 셀프호스티드 러너가 갑자기 느려지고 CI가 줄줄이 실패한 원인을 Azure B시리즈 VM의 CPU 크레딧 고갈로 추적한 과정
summary: "AKS 위에서 ARC로 운영하던 GitHub Actions 셀프호스티드 러너가 어느 오후 갑자기 큐가 밀리고 CI가 줄줄이 실패하기 시작했다. 러너도, 오토스케일러도, 노드도 모두 정상으로 보였지만 진짜 원인은 B시리즈(burstable) VM의 CPU 크레딧 고갈이었다. 크레딧이 바닥나면 4 vCPU 노드가 사실상 1.6코어로 스로틀되고, 평소 8~10분 걸리던 테스트가 15분 타임아웃에 걸려 전멸한다. 진단 과정과 B시리즈 크레딧의 작동 원리, 그리고 가격을 실제로 조회해보니 non-burstable로 바꾸는 비용이 노드당 월 $3 수준이었다는 반전까지 정리했다."
published: 2026-07-16
modified: 2026-07-16
---

## 배경: 셀프호스티드 러너 구성

먼저 이 장애를 이해하는 데 필요한 만큼만 CI 인프라 구성을 설명한다. GitHub Actions의 기본 hosted runner 대신, AKS 클러스터 위에 [ARC(actions-runner-controller)](https://github.com/actions/actions-runner-controller)의 gha-runner-scale-set으로 셀프호스티드 러너를 직접 운영하는 구성이다.

```
GitHub Actions 큐
      │  (job이 쌓이면)
      ▼
ARC listener ──▶ EphemeralRunner pod 생성 (job 1개 = pod 1개, 끝나면 소멸)
      │            · maxRunners: 10 (동시 실행 상한)
      ▼
runner 전용 노드풀 (taint 격리, 오토스케일 0~10 노드)
      · VM SKU: Standard_B4s_v2  ← 오늘의 주인공
```

동작 방식을 요약하면:

- **ephemeral 러너**: job 하나당 러너 pod 하나가 뜨고, job이 끝나면 pod가 사라진다. 상태가 남지 않아 깨끗하지만, 매 job마다 pod 스케줄링이 일어난다
- **2단 오토스케일**: 큐 깊이에 따라 ARC가 러너 pod 수를 조절하고(상한 `maxRunners: 10`), pod가 노드에 안 들어가면 cluster autoscaler가 노드를 추가한다(0~10 노드)
- **노드풀 분리**: 러너 노드풀에 taint를 걸어 앱 워크로드와 격리. CI가 아무리 몰려도 서비스 pod에 영향이 없다

여기서 러너 노드풀의 VM을 `Standard_B4s_v2`로 골랐다. "CI는 하루 종일 도는 게 아니니까 burstable이 싸고 합리적"이라는, 그 자체로는 틀리지 않은 판단이었다. 이 선택이 어떤 조건에서 무너지는지가 이 글의 주제다.

## 증상: 러너가 죽은 것도 아닌데 CI가 전멸

어느 날 오후, 팀 레포의 CI가 이상해졌다. 증상은 세 가지였다.

- PR을 올려도 CI가 30~40분씩 큐에 머물러 있음
- 어떤 워크플로우 run은 두 시간 넘게 `in_progress` 상태
- 테스트 job들이 줄줄이 실패 (정확히는 `cancelled`)

## 1차 확인: 전부 정상으로 보인다

먼저 의심한 건 당연히 "러너가 죽었나"였다.

```bash
gh api repos/<org>/<repo>/actions/runners \
  -q '.runners[] | [.name, .status, (.busy|tostring)] | @tsv'
```

러너 10개 전부 `online`, 전부 `busy`. 죽은 게 아니라 포화였다. k8s 쪽도 확인해봤다.

```bash
kubectl get autoscalingrunnerset -A \
  -o custom-columns='NAME:.metadata.name,MIN:.spec.minRunners,MAX:.spec.maxRunners,CURRENT:.status.currentRunners'
```

`maxRunners: 10`에 current 10. 상한에 딱 걸려 있었다. 노드풀도 autoscale 설정이 살아 있고, 노드 리소스도 CPU 81% 수준으로 높긴 하지만 터질 정도는 아니었다.

여기까지의 결론은 "PR이 몰려서 큐가 밀렸을 뿐, 기다리면 풀린다"였다. 그런데 이 결론으로는 설명이 안 되는 게 하나 있었다. **왜 테스트들이 실패하지?** 큐가 밀리면 느려질 뿐이지, 실패할 이유는 없다.

## 2차 확인: 실패한 job들의 수상한 공통점

실패한 run들을 job 단위로 뜯어봤다.

```bash
gh run view <run-id> --json jobs \
  -q '.jobs[] | [.name, .conclusion, .startedAt, .completedAt] | @tsv'
```

테스트 shard들의 conclusion이 `failure`가 아니라 `cancelled`였고, 실행 시간이 전부 **15분 2x초**로 소름 돋게 균일했다. 워크플로우를 열어보니:

```yaml
test:
  timeout-minutes: 15
```

GitHub Actions에서 `timeout-minutes`를 초과한 job의 conclusion은 `failure`가 아니라 `cancelled`다. 즉 테스트가 깨진 게 아니라, **테스트가 느려져서 타임아웃에 걸려 죽고 있었다**.

그럼 평소엔 얼마나 걸렸나? 장애 직전의 성공한 run을 찾아 비교해보니 같은 테스트 shard가 8~10분이었다. 몇 시간 만에 실행 시간이 1.5배 이상 늘어난 것이다. 코드가 갑자기 느려졌을 리는 없고, 러너의 연산 능력 자체가 떨어졌다는 뜻이다.

> [!note] 두 시간짜리 run의 정체
> "몇 시간째 도는 run"도 여기서 풀렸다. job이 행에 걸린 게 아니라 (1) 슬롯 포화로 run 내부의 순차 job들이 각각 30~50분씩 큐 대기 (2) 타임아웃으로 죽은 shard를 사람들이 re-run하면서 늘어진 것. 그리고 그 재실행이 다시 부하를 키우는 악순환이었다.

## 범인: B시리즈 VM의 CPU 크레딧

러너 노드풀의 VM SKU는 `Standard_B4s_v2`. Azure B시리즈는 **burstable** VM이다. 이 "burstable"의 의미를 정확히 알아야 이 장애가 이해된다.

### B시리즈의 작동 원리

B4s_v2는 명목상 4 vCPU지만, 항상 4코어를 풀로 쓸 수 있는 VM이 아니다.

- **baseline**: 상시 보장되는 성능은 4 vCPU의 40% (약 1.6코어 상당). 대신 가격이 저렴하다
- **크레딧 적립**: CPU 사용량이 baseline보다 낮으면 그 차이만큼 크레딧이 쌓인다. 한가할 때 저축하는 셈
- **버스트**: baseline 이상의 성능이 필요하면 크레딧을 소모하며 4코어를 풀로 쓴다
- **고갈 시 스로틀**: 크레딧이 바닥나면 Azure가 성능을 baseline까지 강제로 깎는다. 4코어 VM이 사실상 1.6코어가 된다

CI 러너처럼 "가끔 몰아서 쓰는" 워크로드에는 이 모델이 비용 효율적이다. 문제는 부하가 **지속**될 때다. 몇 시간 내리 풀부하로 돌면 저축을 꺼내 쓰기만 하다가 바닥이 나고, 그 순간부터 모든 것이 절반 이하 속도로 돌아간다.

앞서 본 러너 구성이 이 조건을 정확히 만들어냈다. 러너 pod의 리소스가 request 500m / limit 3500m으로 잡혀 있어서, 4 vCPU 노드 하나에 pod가 6~7개까지 빽빽하게 스케줄되지만 각 pod는 필요하면 3.5코어까지 쓰려 든다. PR이 몰린 날에는 maxRunners 10개가 노드 2대에 눌러 담긴 채 몇 시간 연속으로 CPU를 80% 이상 점유했고, baseline 40%를 훨씬 넘는 이 사용률이 크레딧을 일방적으로 소모했다.

### 메트릭으로 확인

Azure Monitor의 `CPU Credits Remaining` 메트릭을 러너 노드풀의 VMSS에 대해 조회했다.

```bash
az monitor metrics list \
  --resource <runner-vmss-resource-id> \
  --metric "CPU Credits Remaining" \
  --interval PT15M --offset 4h \
  --query "value[0].timeseries[0].data[].[timeStamp,average]" -o tsv
```

결과가 그림처럼 명확했다.

| 시각 | 크레딧 잔량 |
|---|---|
| 06:09 | 41.1 |
| 06:24 | 24.0 |
| 06:39 | 7.3 |
| 06:54 | 2.4 |
| 이후 | ~3 (바닥에서 횡보) |

크레딧이 바닥난 06:54 전후가 정확히 테스트들이 타임아웃에 걸리기 시작한 시점과 일치했다. 장애의 전체 연쇄는 이렇다.

```
PR 러시 → 러너 노드 몇 시간 연속 고부하
  → CPU 크레딧 고갈 → baseline(40%)으로 스로틀
  → 테스트 8~10분 → 15분+ 로 느려짐
  → timeout-minutes: 15 에 걸려 shard 전멸 (conclusion: cancelled)
  → 개발자들이 re-run → 부하 가중 → 악순환
```

흥미로운 건 같은 클러스터의 앱용 노드풀(같은 B4s_v2)은 크레딧이 최대치로 꽉 차 있었다는 점이다. 앱 워크로드는 부하가 낮아 크레딧이 계속 적립되는 구조라 B시리즈가 오히려 최적이었다. 잘못된 건 SKU 자체가 아니라 **"쉬는 시간이 필요한 VM"에 "몇 시간 연속 풀부하" 워크로드를 올린 조합**이었다.

## 반전: non-burstable과의 가격 차이는 월 $3

"burstable이니까 쌌겠지, non-burstable로 바꾸면 비용이 확 뛰겠지"라고 생각했는데, [Azure Retail Prices API](https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices/azure-retail-prices)로 실제 가격을 조회해보니 예상과 달랐다. Korea Central, Linux, 종량제 기준:

| SKU | 시간당 | B4s_v2 대비 | 비고 |
|---|---|---|---|
| B4s_v2 | $0.208 | - | 4vCPU/16GB, burstable |
| **D4as_v5 (AMD)** | **$0.212** | **+2%** | 4vCPU/16GB, 상시 풀성능 |
| D4s_v5 (Intel) | $0.236 | +13% | 4vCPU/16GB, 상시 풀성능 |
| F4s_v2 | $0.192 | -8% | 4vCPU/8GB, RAM 절반 |

D4as_v5(AMD 기반)로 바꾸면 **노드당 월 $3 차이**로 크레딧 문제가 사라진다. 러너 노드풀은 어차피 autoscale 0~10이라 한가할 땐 0으로 줄어드니 실제 추가 비용은 더 작다. 감으로 "1.6~2배쯤 하겠지"라고 판단했다면 틀렸을 것이다. 가격은 감이 아니라 API로 확인하자.

> [!tip] AKS 노드풀은 SKU 변경이 안 된다
> 기존 노드풀의 VM 크기는 바꿀 수 없다. 새 노드풀을 추가하고 워크로드의 nodeSelector/taint 대상을 옮긴 뒤 기존 풀을 지우는 방식으로 이전해야 한다.

실제로 다음 날 이 방식으로 이관을 마쳤다. D4as_v5 노드풀 추가 → ARC helm 릴리스의 `nodeSelector.agentpool` 전환 → 구 풀의 러너들이 진행 중이던 job을 완주하길 기다렸다가 노드풀 삭제. ephemeral 러너 덕분에 CI 중단 없이 끝났고, 하나 걸릴 뻔한 함정은 러너 pod의 nodeSelector가 노드풀 이름을 가리키고 있어서 helm 값을 같이 안 바꾸면 러너 전원이 Pending에 빠진다는 점이었다.

## 배운 것들

**burstable VM에는 "듀티 사이클" 관점이 필요하다.** 평균 사용률이 낮아도, 부하가 baseline 이상으로 몇 시간 지속될 수 있는 워크로드라면 크레딧이 바닥나는 시나리오를 계산해봐야 한다. CI 러너는 팀이 바쁜 날 정확히 그 패턴이 된다.

**타임아웃 기반 실패는 인프라 성능 저하의 후행 지표다.** `cancelled`가 균일한 실행 시간으로 반복되면 코드가 아니라 러너를 의심하자. 성공하던 시절의 실행 시간과 비교하는 것이 가장 빠른 판별법이었다.

**"러너 online, 오토스케일 정상, 노드 Ready"는 성능 저하를 배제해주지 않는다.** 상태(status)는 전부 초록불이어도 처리량은 절반일 수 있다. B시리즈를 쓴다면 `CPU Credits Remaining`을 모니터링 대상에 넣어두는 게 좋다. 크레딧 잔량에 알림을 걸어두면 이번 같은 장애는 스로틀이 시작되기 30분 전에 미리 알 수 있었다.

**포화 상태에서 동시 실행 수(maxRunners)를 올리는 건 역효과다.** 장애 초기에 "슬롯이 모자라니 maxRunners를 올리자"고 판단할 뻔했는데, 크레딧 고갈 상태에서 같은 노드에 러너 밀도만 높이면 전체가 더 느려진다. 병목이 슬롯인지 연산 능력인지 먼저 구분해야 한다.
