# AWS 아키텍처 설계 — 웹 이벤트 파이프라인

이 문서는 웹 이벤트 파이프라인(이벤트 생성 → 저장 → 시각화)을 AWS에서 운영할 때의 아키텍처를 설명합니다.

### 레이어 구성

```
[생성]    Web/Mobile  →  EC2 (generator)         ← ECR (컨테이너 이미지)
                ↓
[수집]    API Gateway  →  Kinesis Data Streams  →  Kinesis Firehose
                                                          ↓
[저장]    S3 (Raw)  ←────────────────────────────────────┘
               ↓ Lambda ETL
          RDS Aurora (PostgreSQL)       S3 (Processed / 차트)
               ↓                              ↓
[분석]    AWS Glue  →  Athena       ECS Fargate (analytics.py)
               ↓                              ↓
[시각화]  QuickSight          S3 + CloudFront    ECS Fargate (Streamlit)

[운영]    CloudWatch  │  IAM  │  VPC  │  Secrets Manager
```

---

## 1. 실행 방법

AWS 환경에서 이 파이프라인을 배포하는 순서입니다.

**필요한 도구**

- AWS CLI v2 (자격증명 설정 완료)
- Docker Desktop
- Terraform 또는 AWS CloudFormation (인프라 프로비저닝용)

**배포 순서**

```bash
# 1. ECR에 컨테이너 이미지 푸시
aws ecr get-login-password --region ap-northeast-2 \
  | docker login --username AWS --password-stdin <account-id>.dkr.ecr.ap-northeast-2.amazonaws.com

docker build -t event-pipeline ./app
docker tag event-pipeline:latest <account-id>.dkr.ecr.ap-northeast-2.amazonaws.com/event-pipeline:latest
docker push <account-id>.dkr.ecr.ap-northeast-2.amazonaws.com/event-pipeline:latest

# 2. Secrets Manager에 DB 자격증명 등록
aws secretsmanager create-secret \
  --name event-pipeline/db-credentials \
  --secret-string '{"username":"eventuser","password":"<your-password>"}'

# 3. RDS Aurora 클러스터 생성 (VPC 프라이빗 서브넷)
aws rds create-db-cluster \
  --db-cluster-identifier event-pipeline-cluster \
  --engine aurora-postgresql \
  --engine-version 16.1 \
  --master-username eventuser \
  --manage-master-user-password

# 4. Kinesis Data Stream 생성
aws kinesis create-stream \
  --stream-name web-events \
  --shard-count 2

# 5. Kinesis Firehose → S3 Raw 버킷 연결
#    (AWS 콘솔 또는 CloudFormation으로 설정)

# 6. ECS Fargate 태스크로 generator / analytics 실행
aws ecs run-task \
  --cluster event-pipeline \
  --task-definition event-generator \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<subnet-id>],securityGroups=[<sg-id>]}"
```

**로컬 개발 및 테스트는 기존 Docker Compose를 그대로 사용합니다.**

```bash
docker compose up --build
```

---

## 2. 스키마 설명

### 선택한 AWS 서비스의 역할 차이

저장소를 S3(Raw), RDS Aurora, S3(Processed) 세 곳으로 분리한 이유는 각각 목적이 다르기 때문입니다.

S3(Raw)는 Kinesis Firehose가 자동으로 적재하는 원본 로그 창고입니다. JSON이든 parquet이든 파일 단위로 그냥 쌓아둡니다. 용량 제한이 없고 저렴해서 "일단 다 보관"하는 용도에 적합합니다. 나중에 스키마가 바뀌더라도 원본이 있으니 재처리가 가능합니다.

RDS Aurora(PostgreSQL)는 Lambda ETL이 S3 원본을 파싱해서 필드별로 INSERT하는 분석용 DB입니다. `event_type`, `user_id`, `created_at`에 인덱스가 걸려 있어서 집계 쿼리가 밀리초 단위로 빠릅니다. SQL 윈도우 함수와 조인이 자유롭게 됩니다.

S3(Processed)는 analytics.py가 생성한 PNG 차트와 집계 결과 CSV를 올려두는 배포용 버킷입니다. CloudFront를 앞에 붙이면 CDN으로 빠르게 서빙할 수 있습니다.

한마디로: S3(Raw)는 창고, RDS는 서랍장, S3(Processed)는 진열대입니다.

### RDS Aurora 테이블 구조

로컬 PostgreSQL과 동일한 스키마를 사용합니다.

```sql
CREATE TABLE events (
    event_id      UUID         PRIMARY KEY,
    event_type    VARCHAR(20)  NOT NULL,   -- page_view | search | purchase | error | logout
    user_id       VARCHAR(20)  NOT NULL,
    session_id    UUID         NOT NULL,
    device        VARCHAR(10),
    browser       VARCHAR(20),
    country       CHAR(2),
    created_at    TIMESTAMP    NOT NULL,
    -- 타입별 전용 필드 (해당 타입 외 NULL)
    page_path     VARCHAR(100),
    referrer      VARCHAR(50),
    duration_sec  INTEGER,
    query         VARCHAR(200),
    product_id    VARCHAR(10),
    product_name  VARCHAR(100),
    amount        NUMERIC(10,2),
    quantity      INTEGER,
    error_code    SMALLINT,
    error_message VARCHAR(100)
);

CREATE INDEX idx_events_type    ON events(event_type);
CREATE INDEX idx_events_user    ON events(user_id);
CREATE INDEX idx_events_created ON events(created_at);
```

---

## 3. 구현하면서 고민한 점

### 수집 경로: 이벤트를 RDS에 직접 쓸까, Kinesis를 거칠까

가장 먼저 고민한 부분입니다. 직접 INSERT하면 구현은 단순하지만, 트래픽이 갑자기 몰릴 때 RDS 커넥션 풀이 고갈되고 DB가 병목이 됩니다. Kinesis를 중간에 두면 이벤트가 스트림에 쌓이고, downstream(Lambda, Firehose)이 자기 속도로 소화할 수 있습니다. 특히 Firehose로 S3에도 동시에 적재해두면, RDS 스키마가 나중에 바뀌어도 원본으로 재처리가 가능하다는 점이 결정적이었습니다.

### 분석 실행: Lambda vs ECS Fargate

analytics.py는 matplotlib 차트 생성 + 여러 SQL 순차 실행으로 수 분이 걸릴 수 있습니다. Lambda는 실행 시간이 최대 15분으로 제한되고, matplotlib 등 패키지를 포함하면 250MB 용량 제한에도 걸립니다. ECS Fargate는 기존 Docker 이미지를 그대로 올리면 되고 실행 시간 제한이 없습니다. AWS Glue로 매일 새벽 스케줄을 걸어 자동 갱신하도록 설계했습니다.

### 잘 모르는 부분: Kinesis 샤드 수 결정

Kinesis Data Streams의 샤드 수를 얼마로 잡아야 할지 기준이 명확하지 않았습니다. 샤드 하나가 초당 1MB 또는 1,000건을 처리할 수 있다는 문서를 읽고, 5,000건 배치 기준으로는 샤드 2개가 충분하다고 판단해 일단 2로 설정했습니다. 실제 서비스에서는 CloudWatch의 `WriteProvisionedThroughputExceeded` 메트릭을 보면서 조정해야 한다는 것을 찾았고, 프로덕션이라면 Auto Scaling 설정이 필요하다는 점도 확인했습니다.
