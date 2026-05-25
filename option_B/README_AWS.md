# AWS 아키텍처 설계 — 웹 이벤트 파이프라인

## 구성도 레이어 요약

```
[생성]  Web/Mobile  →  EC2 (generator)        ← ECR (이미지)
           ↓
[수집]  API Gateway  →  Kinesis Data Streams  →  Kinesis Firehose
                                                       ↓
[저장]  S3 (Raw)  ←──────────────────────────────────-┘
            ↓ Lambda ETL
        RDS Aurora (PostgreSQL)    S3 (Processed / 차트)
           ↓
[분석]  AWS Glue  →  Athena   ECS Fargate (analytics.py)
                                       ↓
[시각화]  QuickSight    S3+CloudFront    ECS Fargate (Streamlit)

[운영]  CloudWatch  │  IAM  │  VPC  │  Secrets Manager
```

---

## AWS 서비스 구성 및 선택 이유

### 생성 레이어

| 서비스 | 역할 | 선택 이유 |
|---|---|---|
| EC2 | generator.py 컨테이너 실행 | 장기 실행 프로세스를 안정적으로 유지, 인스턴스 크기 자유 조정 |
| ECR | 컨테이너 이미지 저장소 | ECS/EC2에서 바로 pull 가능, IAM으로 접근 제어 |

### 수집 레이어

| 서비스 | 역할 | 선택 이유 |
|---|---|---|
| API Gateway | REST 엔드포인트 | 클라이언트가 HTTP로 이벤트를 푸시할 때 진입점. 인증·스로틀링 내장 |
| Kinesis Data Streams | 실시간 스트림 버퍼 | 초당 수만 건 이벤트를 유실 없이 받아 downstream에 전달 |
| Kinesis Firehose | S3 자동 적재 | 버퍼링 + 배치 압축(parquet/gzip)으로 S3에 자동 전송, 코드 없음 |

### 저장 레이어

| 서비스 | 역할 | 선택 이유 |
|---|---|---|
| S3 (Raw zone) | 원본 이벤트 파일 보관 | 무한 확장, 저렴한 비용, Athena와 직접 연동 |
| RDS Aurora (PostgreSQL) | 구조화된 필드 단위 저장 | 기존 과제와 동일한 PostgreSQL 방언 유지, Multi-AZ 자동 장애복구 |
| Lambda | ETL 변환 | S3 트리거로 서버리스 실행, 짧은 파싱·검증 작업에 최적 |
| S3 (Processed) | 집계 결과 및 차트 PNG 보관 | CloudFront 오리진으로 사용, 정적 콘텐츠 서빙 비용 최소화 |

### 분석 레이어

| 서비스 | 역할 | 선택 이유 |
|---|---|---|
| AWS Glue | ETL 스케줄링 + 데이터 카탈로그 | Athena가 S3 데이터 구조를 인식하려면 카탈로그 필요. 배치 집계 자동화 |
| Athena | S3 위 SQL 집계 | 서버 없이 SQL만으로 parquet 분석, 사용한 데이터량만 과금 |
| ECS Fargate | analytics.py 실행 | 서버 관리 없이 컨테이너 실행, 분석 완료 후 자동 종료로 비용 절감 |

### 시각화 레이어

| 서비스 | 역할 | 선택 이유 |
|---|---|---|
| QuickSight | BI 대시보드 | Athena·RDS 직접 연결, 드래그앤드롭 차트 구성, 추가 서버 불필요 |
| S3 + CloudFront | 차트 PNG 정적 서빙 | analytics.py가 생성한 PNG를 CDN으로 배포, 레이턴시 최소화 |
| ECS Fargate | Streamlit 앱 | Python 기반 인터랙티브 대시보드, 기존 코드 재사용 가능 |

### 운영 레이어

| 서비스 | 역할 | 선택 이유 |
|---|---|---|
| CloudWatch | 메트릭·로그·알람 | EC2/ECS/RDS/Lambda 로그를 한 곳에서 수집, 에러율 임계 알람 |
| IAM | 권한 관리 | 서비스 간 최소 권한 원칙 적용, 자격증명 코드 미포함 |
| VPC | 네트워크 격리 | RDS·Fargate를 프라이빗 서브넷에 배치, 외부 직접 접근 차단 |
| Secrets Manager | DB 자격증명 보관 | 코드에 패스워드 하드코딩 없이 런타임에 안전하게 주입 |

---

## AWS 서비스 역할 차이

### Kinesis Data Streams vs Kinesis Firehose

**Data Streams**는 실시간 데이터를 받아서 여러 소비자가 동시에 읽을 수 있게 해주는 "버퍼 파이프"입니다. 데이터가 들어오는 순간부터 소비자가 직접 읽어야 하고, 정확히 언제 얼마나 처리할지 내가 제어합니다.

**Firehose**는 그 위에 올라타는 "자동 배달부"입니다. 설정한 시간(예: 60초)이나 용량(예: 5MB)이 차면 알아서 S3나 Redshift에 전달하고 종료됩니다. 코드를 전혀 안 써도 됩니다.

한마디로: Data Streams는 내가 운전하는 차, Firehose는 목적지만 정해두면 알아서 가는 택시입니다.

### S3 vs RDS Aurora

**S3**는 파일 단위 오브젝트 스토리지입니다. JSON이든 parquet이든 이미지든 통째로 넣고 꺼냅니다. SQL로 필드를 조회하려면 Athena 같은 도구가 별도로 필요합니다. 용량 제한이 사실상 없고 저렴합니다.

**RDS Aurora**는 행과 열로 쪼개진 관계형 DB입니다. `SELECT event_type, COUNT(*) FROM events WHERE created_at > '2025-01-01'` 같은 쿼리를 바로 실행할 수 있고, 인덱스·트랜잭션·조인이 전부 됩니다. 단, 용량을 미리 프로비저닝해야 하고 S3보다 비쌉니다.

한마디로: S3는 창고(원본 보관), RDS는 서랍장(정리된 검색용 데이터)입니다.

### Lambda vs ECS Fargate

**Lambda**는 이벤트 하나가 들어오면 함수 하나가 실행되고 끝납니다. 실행 시간이 최대 15분으로 제한되고, 상태를 유지할 수 없습니다. S3에 파일이 하나 올라올 때마다 파싱하는 ETL 같은 짧은 작업에 맞습니다.

**ECS Fargate**는 컨테이너를 오래, 지속적으로 실행합니다. analytics.py처럼 DB에 연결해서 쿼리 4개를 돌리고 차트를 그리는 작업은 수 분이 걸릴 수 있는데, 이런 배치 작업이나 항상 켜져 있어야 하는 Streamlit 앱에 적합합니다. 비유하자면 Lambda는 단발성 심부름꾼, Fargate는 자리를 지키고 있는 직원으로 표현할 수 있습니다.

### Athena vs RDS (쿼리 관점)

**Athena**는 S3에 있는 parquet 파일을 SQL로 쿼리합니다. 서버가 없고 스캔한 데이터량(TB당 약 $5)으로만 과금됩니다. 대용량 분석에 유리하지만, 매번 S3를 스캔하므로 빠른 응답이 필요한 서비스에는 부적합합니다.

**RDS**는 이미 인덱스가 걸려 있는 테이블에서 쿼리하므로 응답이 밀리초 단위로 빠릅니다. 대신 항상 켜져 있어야 해서 고정 비용이 발생합니다.

---

## 설계에서 고민한 부분

### 1. 수집 경로: API Gateway → Kinesis vs 직접 RDS 쓰기

가장 먼저 고민한 것은 "이벤트를 RDS에 바로 INSERT하기, 혹은 Kinesis를 거치기"였습니다.

직접 쓰는 방식은 구현이 단순하지만, 트래픽이 갑자기 몰릴 때 RDS 커넥션 풀이 고갈되거나 DB가 병목이 됩니다. Kinesis를 중간에 두면 트래픽을 버퍼링해서 downstream이 자기 속도로 소화할 수 있습니다. 또 Firehose로 S3에도 동시에 적재해두면, 나중에 RDS 스키마가 바뀌더라도 원본 데이터를 다시 재처리할 수 있는 안전망이 생깁니다.

따라서, **수집과 저장을 분리**하는 것이 운영 안정성과 재처리 유연성 모두에 유리합니다.

### 2. 저장소 이중화: S3(Raw) + RDS

S3에만 저장하고 Athena로 분석하는 것이 더 단순해 보이지만, 이번 과제처럼 "필드를 구분해서 저장"하고 "복잡한 집계 쿼리를 빠르게 실행"해야 한다면 RDS가 필요합니다. 그렇다고 RDS만 쓰면 원본 로그를 잃을 위험이 있습니다. S3(원본 보관)와 RDS(분석용 구조화)를 함께 두는 것이 실제 프로덕션 환경에서 일반적인 패턴입니다.

### 3. 분석 실행 방식: Lambda vs ECS Fargate

analytics.py는 matplotlib으로 차트를 그리고 여러 SQL을 순차 실행하는데, 이를 Lambda에 넣으면 실행 시간 초과 + 패키지 용량 제한(250MB)에 걸릴 수 있습니다. Fargate는 컨테이너 이미지를 그대로 사용하므로 기존 Docker 파이프라인을 그대로 이식할 수 있고, 실행 시간 제한도 없습니다. Glue로 스케줄을 걸어 매일 새벽 집계 결과를 자동 갱신하도록 구성했습니다.

### 4. 시각화 도구 3개 병렬 제시 이유

QuickSight(관리자용 BI), S3+CloudFront(외부 공유용 정적 이미지), Streamlit(개발자용 인터랙티브)는 각각 사용 목적이 다릅니다. 실제 팀에서는 BI 툴 라이선스 비용, 외부 공개 여부, 커스텀 UI 필요도에 따라 하나를 선택하거나 조합합니다. 선택지를 열어두는 것이 현실적이라고 판단했습니다.
