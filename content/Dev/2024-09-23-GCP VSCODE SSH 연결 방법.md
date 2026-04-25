---
title: GCP VM과 VS Code SSH 연결 설정 가이드
date: 2024-09-23
tags:
- gcp
- vscode
- ssh
- cloud
- remote-development
- google-cloud
draft: false
enableToc: true
description: Google Cloud Platform VM 인스턴스에 SSH 키를 생성하고 VS Code로 원격 연결하는 방법
summary: "GCP(Google Cloud Platform) VM 인스턴스에 SSH 키 페어를 생성하고 등록하여 VS Code에서 원격 접속하는 전체 과정을 설명한다. ssh-keygen으로 로컬에서 키를 생성하고, GCP Console에서 공개 키를 VM에 등록한 후, VS Code의 Remote Explorer 설정을 통해 편리하게 원격 개발 환경을 구축할 수 있다. 터미널과 VS Code 두 가지 방법으로 접속을 확인한다."
published: 2024-09-23
modified: 2024-09-23
---
### Metadata-managed SSH connections
https://cloud.google.com/compute/docs/instances/ssh#third-party-tools


### Create an SSH key pair
https://cloud.google.com/compute/docs/connect/create-ssh-keys#console



## SSH 키 페어 생성

#### Mac/Linux 유저:

```shell
ssh-keygen -t rsa -f ~/.ssh/KEY_FILENAME -C USERNAME
```


### Windows 유저
```shell
ssh-keygen -t rsa -f C:\Users\WINDOWS_USER\.ssh\KEY_FILENAME -C USERNAME
```

다음을 대체하세요:

- `KEY_FILENAME`: SSH 키 파일의 이름입니다. 예를 들어, `my-ssh-key`라는 파일 이름은 `my-ssh-key`라는 개인 키 파일과 `my-ssh-key.pub`이라는 공개 키 파일을 생성합니다.
- `USERNAME`: VM에서의 사용자 이름입니다. 예를 들어, `cloudysanfrancisco` 또는 `cloudysanfrancisco_gmail_com`과 같습니다. Linux VM의 경우, VM이 root 로그인을 허용하도록 구성하지 않는 한 `USERNAME`은 `root`가 될 수 없습니다. 자세한 내용은 [root 사용자로 VM에 연결하기](https://cloud.google.com/compute/docs/connect/root-ssh)를 참조하세요. Active Directory(AD)를 사용하는 Windows VM의 경우, 사용자 이름 앞에 `DOMAIN\` 형식의 AD 도메인을 붙여야 합니다. 예를 들어, `ad.example.com` AD 내의 `cloudysanfrancisco` 사용자의 `USERNAME`은 `example\cloudysanfrancisco`입니다.

`ssh-keygen`은 개인 키 파일을 `~/.ssh/KEY_FILENAME`에, 공개 키 파일을 `~/.ssh/KEY_FILENAME.pub`에 저장합니다. `cloudysanfrancisco` 사용자의 공개 키는 다음과 유사하게 보입니다:



	 아래와 같이 설정하여 실행함:
	`KEY_FILENAME`: podly_gcp_ssh
	`USERNAME:`: syshin0116

```
ssh-keygen -t rsa -f ~/.ssh/podly_gcp_ssh -C syshin0116
```


![](https://i.imgur.com/wdkdzoL.png)
> passphase는 추가 비밀번호를 걸어 보안을 강화하는건데 귀찮아서 넘겼다(ENTER)

![](https://i.imgur.com/jUERlTx.png)
주어진 경로를 확인해보면 설정한 파일명(podly_gcp_ssh)으로 생성된걸 확인할 수 있다:

![](https://i.imgur.com/R631NQ1.png)

## GCP VM에 생성한 SSH 등록

### 1. GCP Console에서 VM 선택

![](https://i.imgur.com/lGWVrnF.png)

상단에 수정 클릭:

![](https://i.imgur.com/tkdMV2q.png)

SSH Key 부분에 이전에 생성한 SSH key(`파일명.pub` 의 내용)을 복사해서 넣어주면 된다:

![](https://i.imgur.com/JNsPxA1.png)
![](https://i.imgur.com/NKVpVh0.png)



## 접속 확인

### 터미널 접속

Key 권한 설정: 습관이 되어서 했는데, 필요한지 모르겠다...
```shell
chmod 600 /Users/syshin/.ssh/podly_gcp_ssh
chmod 600 /Users/syshin/.ssh/podly_gcp_ssh.pub
```

private 키와 유저네임을 통해 접속
> `.pub`가 없는게 private 키다

```shell
ssh -i PATH_TO_PRIVATE_KEY USERNAME@EXTERNAL_IP
```


```shell
ssh -i /Users/syshin/.ssh/podly_gcp_ssh syshin0116@34.64.181.98
```

![](https://i.imgur.com/6jmYX8Q.png)

### VS Code 접속

### Remote Explorer config 파일 설정


![](https://i.imgur.com/xAvmQnf.png)

예시 config:
```
Host Podly
    HostName 34.64.181.98
    IdentityFile /Users/syshin/.ssh/podly_gcp_ssh
    User syshin0116
```

![](https://i.imgur.com/NuuzBzW.png)
![](https://i.imgur.com/uoUFpf1.png)
쫜~