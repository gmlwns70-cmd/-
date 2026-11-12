"""API 키 없이 디자인을 확인하는 샘플 원고 (수치가 들어간 카드는 일부러 넣지 않았습니다)."""

SAMPLE_SCRIPT = {
    "topic": "줄 서던 가게가 금방 조용해지는 이유",
    "target": "자영업 사장님",
    "brand": "@my_brand",
    "total_cards": 15,
    "cards": [
        {
            "no": 1, "role": "표지", "type": "cover",
            "lines": [
                {"text": "줄 서던 가게가", "highlight": False},
                {"text": "금방 조용해지는 이유", "highlight": True},
            ],
            "image_prompt": "upper body, holding an empty order pad and a pen, looking sideways in surprise",
            "emotion": "당황", "source": {"name": "", "url": ""},
            "verify_needed": False,
        },
        {
            "no": 2, "role": "흔한 믿음", "type": "text",
            "lines": [
                {"text": "“맛있으면", "highlight": False},
                {"text": "손님은 알아서", "highlight": False},
                {"text": "다시 온다”", "highlight": False},
                {"text": "", "highlight": False},
                {"text": "혹시 이렇게", "highlight": False},
                {"text": "생각하고 계시진", "highlight": False},
                {"text": "않나요?", "highlight": False},
            ],
            "image_prompt": "", "emotion": "", "source": {"name": "", "url": ""},
            "verify_needed": False,
        },
        {
            "no": 4, "role": "반전", "type": "illustrated",
            "lines": [
                {"text": "그런데 문제는", "highlight": False},
                {"text": "처음 온 손님이", "highlight": False},
                {"text": "다시 오지 않는다는", "highlight": True},
                {"text": "거예요", "highlight": False},
            ],
            "image_prompt": "upper body, hand on cheek, looking down at a phone with a worried face",
            "emotion": "걱정", "source": {"name": "", "url": ""},
            "verify_needed": False,
        },
        {
            "no": 5, "role": "핵심 통찰", "type": "text",
            "lines": [
                {"text": "손님이 다시 오는 건", "highlight": False},
                {"text": "맛 때문이 아니라", "highlight": False},
                {"text": "기억에 남았기", "highlight": True},
                {"text": "때문이에요", "highlight": True},
            ],
            "image_prompt": "", "emotion": "", "source": {"name": "", "url": ""},
            "verify_needed": False,
        },
    ],
}
