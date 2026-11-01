"""Prompt presets: genres, styles and their prompt fragments."""
from __future__ import annotations

from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Production genres (C4) + negatives per genre (C5)
# ---------------------------------------------------------------------------

GENRES: List[Dict[str, Any]] = [
    {
        "id": "ad_product",
        "label": "Publicidade de produto",
        "structure": (
            "hero product photography — subject as the star, controlled environment, "
            "studio or lifestyle set, precise lighting on materials, brand-quality finish"
        ),
        "negative": (
            "deformed product, warped logo, extra parts, wrong proportions, "
            "missing details, blurry label, reflections of camera, plastic look"
        ),
    },
    {
        "id": "editorial_fashion",
        "label": "Editorial de moda",
        "structure": (
            "fashion editorial — model, styling, expressive pose, magazine cover feel, "
            "cinematic color grade, negative space for text"
        ),
        "negative": (
            "extra fingers, deformed hands, unnatural pose, cheap look, "
            "oversaturated, warped garment, bad anatomy"
        ),
    },
    {
        "id": "architecture",
        "label": "Arquitetura",
        "structure": (
            "architectural photography — strong geometry, clean lines, scale reference, "
            "natural or golden light, landscape orientation, realistic materials"
        ),
        "negative": (
            "crooked lines, warped perspective, unrealistic scale, distorted windows, "
            "cluttered scene, oversharpened, floating elements"
        ),
    },
    {
        "id": "gastronomy",
        "label": "Gastronomia",
        "structure": (
            "food photography — appetizing texture, steam, garnish detail, "
            "warm directional light, shallow depth of field, styling composition"
        ),
        "negative": (
            "soggy look, plastic food, burnt edges, unappetizing, wrong color of ingredients, "
            "overcooked, flat lighting"
        ),
    },
    {
        "id": "portrait",
        "label": "Retrato editorial",
        "structure": (
            "editorial portrait — natural skin texture, expressive eyes, "
            "controlled light (window/softbox), shallow DOF, genuine expression"
        ),
        "negative": (
            "waxy skin, extra fingers, deformed hands, bad anatomy, double chin, "
            "oversmoothed, uncanny expression, deformed ears"
        ),
    },
    {
        "id": "brand_scene",
        "label": "Cena de marca",
        "structure": (
            "brand lifestyle scene — product integrated in a real environment, "
            "aspirational mood, consistent palette, storytelling composition"
        ),
        "negative": (
            "inconsistent branding, wrong logo, cluttered, cheap stock feel, "
            "distracting background, off-brand colors"
        ),
    },
]

GENRE_BY_SUBJECT: Dict[str, str] = {
    "pessoa": "portrait",
    "moda": "editorial_fashion",
    "objeto_produto": "ad_product",
    "food": "gastronomy",
    "ambiente_arquitetura": "architecture",
    "veiculo": "ad_product",
    "paisagem": "architecture",
    "animal": "portrait",
}

SUBJECT_TYPES: List[Dict[str, str]] = [
    {"value": "livre", "label": "Livre"},
    {"value": "pessoa", "label": "Pessoa"},
    {"value": "objeto_produto", "label": "Objeto / Produto"},
    {"value": "food", "label": "Comida"},
    {"value": "animal", "label": "Animal"},
    {"value": "ambiente_arquitetura", "label": "Ambiente / Arquitetura"},
    {"value": "veiculo", "label": "Veículo"},
    {"value": "abstrato", "label": "Abstrato"},
    {"value": "paisagem", "label": "Paisagem"},
    {"value": "moda", "label": "Moda"},
]

REFERENCE_PURPOSES: List[str] = [
    "Estilo", "Cores", "Iluminação", "Fundo", "Roupa", "Produto",
    "Textura", "Composição", "Pose",
]

SEMANTIC_ROLES: List[Dict[str, Any]] = [
    {
        "value": "object_primary", "label": "O Produto / Objeto",
        "description": "O elemento central da imagem — forma e detalhes preservados",
        "default_authority": "authoritative", "fidelity": 95,
        "keep": ["Composição", "Textura", "Estilo"], "vary": [],
        "weights": {"colors": 90, "lighting": 60, "composition": 50, "textures": 95},
    },
    {
        "value": "context_application", "label": "O Ambiente / Cenário",
        "description": "O cenário onde o objeto será integrado",
        "default_authority": "contextual", "fidelity": 60,
        "keep": ["Composição", "Iluminação"], "vary": ["Fundo", "Estilo"],
        "weights": {"colors": 60, "lighting": 80, "composition": 90, "textures": 50},
    },
    {
        "value": "style_reference", "label": "O Estilo Visual",
        "description": "A linguagem visual, paleta e estética a seguir",
        "default_authority": "contextual", "fidelity": 70,
        "keep": ["Paleta de cores", "Estilo"], "vary": ["Composição", "Fundo"],
        "weights": {"colors": 95, "lighting": 70, "composition": 40, "textures": 80},
    },
    {
        "value": "lighting_reference", "label": "A Iluminação / Clima",
        "description": "O tipo de luz, atmosfera e mood",
        "default_authority": "contextual", "fidelity": 65,
        "keep": ["Iluminação", "Atmosfera"], "vary": ["Composição", "Fundo", "Estilo"],
        "weights": {"colors": 50, "lighting": 95, "composition": 30, "textures": 40},
    },
]

KEEP_VARY_OPTIONS: List[str] = [
    "Composição", "Paleta de cores", "Iluminação", "Estilo", "Textura",
    "Pose", "Atmosfera", "Fundo",
]

VISUAL_STYLES: List[str] = [
    "Fotorrealista", "Cinematográfico", "Ilustração Digital", "3D Render",
    "Minimalista", "Luxo", "Anime", "Aquarela", "Flat/Vetor", "Pixel Art",
    "Pintura a Óleo", "Cyberpunk", "Arte Fantasia", "Retrô/Vintage",
    "Pop Art", "Surreal", "Editorial", "Concept Art",
]

STYLE_DESCRIPTIONS: Dict[str, str] = {
    "Fotorrealista": "Produtos, pessoas e cenas com materiais e luz naturais.",
    "Cinematográfico": "Narrativa visual, contraste e cor de filme.",
    "Ilustração Digital": "Ilustração limpa com controle de formas e cores.",
    "3D Render": "Objetos e ambientes com acabamento de render 3D.",
    "Minimalista": "Poucos elementos, espaço negativo e composição limpa.",
    "Luxo": "Acabamento premium, materiais ricos e iluminação controlada.",
    "Anime": "Personagens e cenas inspirados em animação japonesa.",
    "Aquarela": "Pinceladas translúcidas, papel e bordas orgânicas.",
    "Flat/Vetor": "Formas planas, contornos claros e aparência vetorial.",
    "Pixel Art": "Blocos de pixels visíveis e paleta limitada.",
    "Pintura a Óleo": "Textura de tinta, pinceladas e profundidade pictórica.",
    "Cyberpunk": "Tecnologia, neon, chuva e atmosfera urbana futurista.",
    "Arte Fantasia": "Mundos imaginários, detalhes épicos e atmosfera fantástica.",
    "Retrô/Vintage": "Cores, textura e acabamento inspirados em décadas passadas.",
    "Pop Art": "Cores fortes, contraste alto e linguagem gráfica expressiva.",
    "Surreal": "Combinações impossíveis e lógica visual de sonho.",
    "Editorial": "Direção de arte de revista, moda e publicidade.",
    "Concept Art": "Exploração de personagens, ambientes e ideias visuais.",
}

MOOD_OPTIONS: List[str] = [
    "Alegre", "Dramático", "Sombrio", "Calmo", "Futurista", "Nostálgico",
]

LENSES: List[str] = [
    "14mm", "24mm", "35mm", "50mm", "85mm", "105mm macro", "135mm", "200mm+",
]

APERTURES: List[str] = ["f/1.4", "f/2.8", "f/5.6", "f/11"]

LIGHTING_OPTIONS: List[str] = [
    "Golden Hour", "Neon", "Studio Softbox", "Natural", "Dramatic",
    "Backlit", "Rim Light", "Volumetric", "Low Key", "High Key",
]

ANGLE_OPTIONS: List[str] = [
    "Top-down", "Frontal", "3/4", "Low Angle", "Eye Level", "Overhead",
    "Worm's Eye",
]

SUBJECT_DISTANCES: List[Dict[str, str]] = [
    {"value": "closeup", "label": "Close-up (detalhes)", "prompt_phrase": "close-up shot, subject fills ~70–85% of the frame"},
    {"value": "portrait", "label": "Retrato / Meio corpo", "prompt_phrase": "medium shot, subject fills ~55–70%"},
    {"value": "american", "label": "Plano americano", "prompt_phrase": "medium-wide shot, subject fills ~45–60%"},
    {"value": "full", "label": "Corpo inteiro", "prompt_phrase": "full-body shot, subject fills ~35–50%"},
    {"value": "wide", "label": "Plano geral (ambiente)", "prompt_phrase": "wide shot, subject fills ~20–35%, background visible"},
]

V4_ASPECT_RATIOS: List[Dict[str, str]] = [
    {"value": "auto", "hint": "Automático"},
    {"value": "1:1", "hint": "Quadrado"},
    {"value": "21:9", "hint": "Ultrapanorâmica"},
    {"value": "16:9", "hint": "Tela panorâmica"},
    {"value": "9:16", "hint": "Story para mídias sociais"},
    {"value": "3:4", "hint": "Tradicional"},
    {"value": "4:5", "hint": "Postagem para mídias sociais"},
    {"value": "5:4", "hint": "Flexível"},
    {"value": "4:3", "hint": "Clássico"},
    {"value": "3:2", "hint": "Padrão"},
    {"value": "2:3", "hint": "Retrato"},
]

PLATFORM_PRESETS: Dict[str, Dict[str, str]] = {
    "feed": {"label": "Feed (Instagram)", "aspect_ratio": "1:1"},
    "story": {"label": "Story (9:16)", "aspect_ratio": "9:16"},
    "post": {"label": "Post vertical (4:5)", "aspect_ratio": "4:5"},
    "youtube": {"label": "YouTube (16:9)", "aspect_ratio": "16:9"},
    "banner": {"label": "Banner (21:9)", "aspect_ratio": "21:9"},
    "twitter": {"label": "X / Twitter (16:9)", "aspect_ratio": "16:9"},
    "blog": {"label": "Blog (3:2)", "aspect_ratio": "3:2"},
    "livestream": {"label": "Live (16:9)", "aspect_ratio": "16:9"},
}

STRUCTURED_FIELDS: Dict[str, List[Dict[str, Any]]] = {
    "livre": [],
    "objeto_produto": [
        {"key": "material", "label": "Material", "type": "chips", "options": ["Metal", "Madeira", "Vidro", "Plástico", "Couro", "Cerâmica", "Tecido", "Papel"]},
        {"key": "dominantColor", "label": "Cor dominante", "type": "text"},
        {"key": "state", "label": "Estado", "type": "chips", "options": ["Novo", "Vintage", "Usado", "Em movimento", "Estático"]},
        {"key": "context", "label": "Contexto", "type": "chips", "options": ["Studio", "Mesa", "Natureza", "Urbano", "Mão segurando", "Em uso"]},
    ],
    "food": [
        {"key": "foodType", "label": "Tipo de comida", "type": "chips", "options": ["Prato pronto", "Ingrediente", "Sobremesa", "Bebida", "Snack", "Saudável"]},
        {"key": "visualTemp", "label": "Temperatura visual", "type": "chips", "options": ["Quente (vapor)", "Frio (condensação)", "Ambiente", "Congelado"]},
        {"key": "presentation", "label": "Apresentação", "type": "chips", "options": ["Emplatado", "Rústico", "Minimalista", "Abundante", "Desconstruído"]},
    ],
    "ambiente_arquitetura": [
        {"key": "space", "label": "Espaço", "type": "chips", "options": ["Interno", "Externo"]},
        {"key": "timeOfDay", "label": "Horário", "type": "chips", "options": ["Manhã", "Meio-dia", "Tarde", "Golden Hour", "Noite", "Blue Hour"]},
        {"key": "weather", "label": "Clima", "type": "chips", "options": ["Céu limpo", "Nublado", "Chuva", "Névoa", "Neve"]},
        {"key": "season", "label": "Estação", "type": "chips", "options": ["Primavera", "Verão", "Outono", "Inverno"]},
    ],
    "animal": [
        {"key": "species", "label": "Espécie", "type": "text"},
        {"key": "phase", "label": "Fase", "type": "chips", "options": ["Filhote", "Adulto", "Idoso"]},
        {"key": "action", "label": "Ação", "type": "chips", "options": ["Parado", "Correndo", "Dormindo", "Comendo", "Brincando", "Voando", "Nadando"]},
    ],
    "pessoa": [
        {"key": "ageGender", "label": "Idade / Gênero", "type": "text"},
        {"key": "expression", "label": "Expressão", "type": "chips", "options": ["Sorrindo", "Sério", "Pensativo", "Confiante", "Relaxado", "Determinado"]},
        {"key": "clothing", "label": "Estilo de roupa", "type": "chips", "options": ["Casual", "Formal", "Esportivo", "Elegante", "Streetwear", "Minimalista"]},
        {"key": "pose", "label": "Pose", "type": "chips", "options": ["De pé", "Sentado", "Andando", "Close-up", "Meio corpo", "Corpo inteiro"]},
    ],
    "moda": [
        {"key": "garment", "label": "Peça", "type": "text"},
        {"key": "fabric", "label": "Tecido", "type": "chips", "options": ["Algodão", "Seda", "Linho", "Couro", "Denim", "Tricô", "Sintético"]},
        {"key": "fashionSeason", "label": "Estação", "type": "chips", "options": ["Primavera/Verão", "Outono/Inverno", "Resort", "Atemporal"]},
        {"key": "fashionStyle", "label": "Abordagem", "type": "chips", "options": ["Editorial", "Comercial", "Streetstyle", "Haute Couture"]},
    ],
    "veiculo": [
        {"key": "vehicleType", "label": "Tipo", "type": "chips", "options": ["Carro", "Moto", "Bicicleta", "Caminhão", "Barco", "Avião"]},
        {"key": "vehicleState", "label": "Estado", "type": "chips", "options": ["Parado", "Em movimento", "Estacionado", "Em curva"]},
        {"key": "vehicleColor", "label": "Cor", "type": "text"},
    ],
    "abstrato": [
        {"key": "abstractStyle", "label": "Estilo abstrato", "type": "chips", "options": ["Fluido", "Geométrico", "Orgânico", "Fractal", "Glitch", "Gradiente"]},
        {"key": "abstractMood", "label": "Mood", "type": "chips", "options": ["Energético", "Calmo", "Misterioso", "Alegre", "Dramático"]},
    ],
    "paisagem": [
        {"key": "landscapeType", "label": "Tipo", "type": "chips", "options": ["Montanha", "Praia", "Floresta", "Deserto", "Cidade", "Campo", "Lago", "Rio"]},
        {"key": "landscapeTime", "label": "Horário", "type": "chips", "options": ["Nascer do sol", "Meio-dia", "Pôr do sol", "Noite", "Blue Hour"]},
        {"key": "landscapeWeather", "label": "Clima", "type": "chips", "options": ["Céu limpo", "Nuvens dramáticas", "Névoa", "Tempestade", "Arco-íris"]},
    ],
}

DEFAULT_NEGATIVES: Dict[str, str] = {
    "livre": "blurry, low quality, watermark, text, deformed, distorted, ugly, bad anatomy",
    "pessoa": "deformed hands, extra fingers, blurry face, watermark, text, low quality, distorted features, unnatural skin",
    "objeto_produto": "text, watermark, blurry, low quality, wrong proportions, distorted shape, bad lighting",
    "food": "unappetizing, blurry, low quality, watermark, text, artificial looking, bad plating",
    "animal": "deformed, extra limbs, blurry, watermark, text, low quality, unnatural anatomy",
    "ambiente_arquitetura": "distorted lines, blurry, watermark, text, low quality, impossible geometry",
    "veiculo": "distorted body, wrong proportions, blurry, watermark, text, low quality",
    "abstrato": "blurry, low quality, watermark, text, muddy colors",
    "paisagem": "blurry, low quality, watermark, text, oversaturated, artificial looking",
    "moda": "deformed hands, extra fingers, distorted fabric, blurry, watermark, text, low quality",
}

GENERIC_NEGATIVE = "blurry, low quality, watermark, text, deformed, distorted, ugly, bad anatomy"

QUALITY_TAGS: Dict[str, str] = {
    "padrao": "",
    "alta": "highly detailed, sharp focus, professional photography",
    "maxima": "highly detailed, sharp focus, professional photography, masterpiece, ultra realistic",
}

PHOTOGRAPHIC_STYLES = {"Fotorrealista", "Cinematográfico", "Luxo"}

SUBJECT_DEFAULTS: Dict[str, Dict[str, str]] = {
    "livre": {"lens": "50mm", "aperture": "f/5.6"},
    "objeto_produto": {"lens": "85mm", "aperture": "f/5.6"},
    "food": {"lens": "50mm", "aperture": "f/2.8"},
    "ambiente_arquitetura": {"lens": "24mm", "aperture": "f/8"},
    "pessoa": {"lens": "85mm", "aperture": "f/2.8"},
    "moda": {"lens": "50mm", "aperture": "f/4"},
    "veiculo": {"lens": "35mm", "aperture": "f/5.6"},
    "animal": {"lens": "85mm", "aperture": "f/2.8"},
    "abstrato": {"lens": "50mm", "aperture": "f/5.6"},
    "paisagem": {"lens": "24mm", "aperture": "f/8"},
}

ZONE_LABELS: Dict[str, str] = {
    "top": "top", "bottom": "bottom", "left": "left", "right": "right",
    "center": "center",
}

INTENSITY_MAP: Dict[str, str] = {
    "Totalmente limpa": "completely clean and empty",
    "Moderadamente limpa": "mostly clean, minimal details",
    "Levemente limpa": "slightly clear, few subtle details",
}

TONE_MAP: Dict[str, str] = {
    "Automática": "automatic",
    "Neutra": "neutral",
    "Quente": "warm",
    "Fria": "cool",
}
