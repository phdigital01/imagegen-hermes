/**
 * ImageGen — names and plain explanations of the direction options, per language.
 *
 * The option values stay as the backend defines them, because they feed the prompt.
 * This table only changes what the person reads in the picker.
 */

import { activeLangOf } from './i18n'

export type DirectionGroup = 'style' | 'lighting' | 'angle' | 'distance' | 'lens' | 'aperture' | 'mood' | 'subject'

type Entry = [label: string, hint: string]
type Table = Partial<Record<DirectionGroup, Record<string, Entry>>>

const PT: Table = {
  subject: {
    livre: ['Livre', ''],
    pessoa: ['Pessoa', ''],
    objeto_produto: ['Produto', ''],
    food: ['Comida', ''],
    moda: ['Moda', ''],
    animal: ['Animal', ''],
    ambiente_arquitetura: ['Ambiente', ''],
    veiculo: ['Veículo', ''],
    abstrato: ['Abstrato', ''],
    paisagem: ['Paisagem', '']
  },
  style: {
    Fotorrealista: ['Fotorrealista', 'Parece uma foto de verdade.'],
    'Cinematográfico': ['Cinematográfico', 'Cor e contraste de cena de filme.'],
    'Ilustração Digital': ['Ilustração digital', 'Desenho limpo, com formas e cores controladas.'],
    '3D Render': ['3D', 'Personagens e objetos com cara de animação 3D.'],
    Minimalista: ['Minimalista', 'Poucos elementos e muito espaço vazio.'],
    Luxo: ['Luxo', 'Materiais nobres e luz controlada.'],
    Anime: ['Anime', 'Traço de animação japonesa.'],
    Aquarela: ['Aquarela', 'Tinta transparente sobre papel.'],
    'Flat/Vetor': ['Vetor', 'Formas chapadas e contornos limpos.'],
    'Pixel Art': ['Pixel art', 'Blocos de pixels, como jogos antigos.'],
    'Pintura a Óleo': ['Pintura a óleo', 'Pinceladas grossas e textura de tela.'],
    Cyberpunk: ['Cyberpunk', 'Neon, chuva e tecnologia futurista.'],
    'Arte Fantasia': ['Fantasia', 'Mundo mágico, cheio de detalhes.'],
    'Retrô/Vintage': ['Retrô', 'Cores e textura de décadas passadas.'],
    'Pop Art': ['Pop art', 'Cores fortes e pontos de impressão.'],
    Surreal: ['Surreal', 'Combinações impossíveis, como num sonho.'],
    Editorial: ['Editorial', 'Direção de arte de revista.'],
    'Concept Art': ['Concept art', 'Pintura solta, de jogos e filmes.']
  },
  lighting: {
    'Golden Hour': ['Pôr do sol', 'Luz baixa, quente e dourada.'],
    Neon: ['Neon', 'Luzes coloridas de letreiro, à noite.'],
    'Studio Softbox': ['Estúdio', 'Luz suave e uniforme de estúdio.'],
    Natural: ['Natural', 'Luz do dia, sem efeito.'],
    Dramatic: ['Dramática', 'Luz forte de um lado, sombra do outro.'],
    Backlit: ['Contraluz', 'A luz vem de trás do assunto.'],
    'Rim Light': ['Luz de contorno', 'Um fio de luz desenha a silhueta.'],
    Volumetric: ['Raios de luz', 'Feixes visíveis na névoa.'],
    'Low Key': ['Escura', 'Fundo escuro e pouca luz.'],
    'High Key': ['Clara', 'Tudo muito claro, quase sem sombra.']
  },
  angle: {
    'Top-down': ['De cima, reto', 'Câmera a 90 graus sobre o assunto.'],
    Frontal: ['De frente', 'Câmera reta, bem de frente.'],
    '3/4': ['Três quartos', 'Meio de lado. Mostra frente e lateral.'],
    'Low Angle': ['De baixo', 'Câmera baixa. O assunto parece imponente.'],
    'Eye Level': ['Altura do olhar', 'Câmera na altura do assunto.'],
    Overhead: ['Do alto', 'Câmera alta, olhando em diagonal.'],
    "Worm's Eye": ['Do chão', 'Câmera no chão, olhando para cima.']
  },
  distance: {
    closeup: ['Close', 'O rosto ou o detalhe enche a imagem.'],
    portrait: ['Meio corpo', 'Da cintura para cima.'],
    american: ['Plano americano', 'Dos joelhos para cima.'],
    full: ['Corpo inteiro', 'O assunto inteiro aparece.'],
    wide: ['Plano geral', 'O ambiente domina. O assunto fica pequeno.']
  },
  lens: {
    '14mm': ['14mm', 'Ultra-angular. Mostra muito e estica as bordas.'],
    '24mm': ['24mm', 'Grande-angular. Bom para ambientes.'],
    '35mm': ['35mm', 'Olhar de reportagem, com o entorno visível.'],
    '50mm': ['50mm', 'Perto da visão humana.'],
    '85mm': ['85mm', 'Lente de retrato. Fundo suave.'],
    '105mm macro': ['105mm macro', 'Detalhes bem de perto.'],
    '135mm': ['135mm', 'Teleobjetiva. Aproxima o fundo.'],
    '200mm+': ['200mm+', 'Tele longa. O fundo vira uma parede de cor.']
  },
  aperture: {
    'f/1.4': ['f/1.4', 'Fundo totalmente desfocado.'],
    'f/2.8': ['f/2.8', 'Fundo desfocado, ainda reconhecível.'],
    'f/5.6': ['f/5.6', 'Fundo levemente suave.'],
    'f/11': ['f/11', 'Tudo em foco, da frente ao fundo.']
  },
  mood: {
    Alegre: ['Alegre', 'Cores vivas e clima de dia bom.'],
    'Dramático': ['Dramático', 'Tensão, contraste e céu carregado.'],
    Sombrio: ['Sombrio', 'Escuro, frio e sem cor.'],
    Calmo: ['Calmo', 'Tons suaves e silêncio.'],
    Futurista: ['Futurista', 'Formas limpas e luzes de tecnologia.'],
    'Nostálgico': ['Nostálgico', 'Cara de foto antiga.']
  }
}

const EN: Table = {
  subject: {
    livre: ['Free', ''],
    pessoa: ['Person', ''],
    objeto_produto: ['Product', ''],
    food: ['Food', ''],
    moda: ['Fashion', ''],
    animal: ['Animal', ''],
    ambiente_arquitetura: ['Interior', ''],
    veiculo: ['Vehicle', ''],
    abstrato: ['Abstract', ''],
    paisagem: ['Landscape', '']
  },
  style: {
    Fotorrealista: ['Photorealistic', 'Looks like a real photo.'],
    'Cinematográfico': ['Cinematic', 'Color and contrast of a film scene.'],
    'Ilustração Digital': ['Digital illustration', 'Clean drawing with controlled shapes and colors.'],
    '3D Render': ['3D', 'Characters and objects with a 3D animation look.'],
    Minimalista: ['Minimalist', 'Few elements and a lot of empty space.'],
    Luxo: ['Luxury', 'Rich materials and controlled light.'],
    Anime: ['Anime', 'Japanese animation line work.'],
    Aquarela: ['Watercolor', 'Transparent paint on paper.'],
    'Flat/Vetor': ['Vector', 'Flat shapes and clean outlines.'],
    'Pixel Art': ['Pixel art', 'Blocks of pixels, like old games.'],
    'Pintura a Óleo': ['Oil painting', 'Thick brush strokes and canvas texture.'],
    Cyberpunk: ['Cyberpunk', 'Neon, rain and futuristic technology.'],
    'Arte Fantasia': ['Fantasy', 'A magical, highly detailed world.'],
    'Retrô/Vintage': ['Retro', 'Colors and texture of past decades.'],
    'Pop Art': ['Pop art', 'Strong colors and print dots.'],
    Surreal: ['Surreal', 'Impossible combinations, like a dream.'],
    Editorial: ['Editorial', 'Magazine art direction.'],
    'Concept Art': ['Concept art', 'Loose painting from games and films.']
  },
  lighting: {
    'Golden Hour': ['Golden hour', 'Low, warm, golden light.'],
    Neon: ['Neon', 'Colored sign lights at night.'],
    'Studio Softbox': ['Studio', 'Soft, even studio light.'],
    Natural: ['Natural', 'Daylight with no effect.'],
    Dramatic: ['Dramatic', 'Hard light on one side, shadow on the other.'],
    Backlit: ['Backlit', 'The light comes from behind the subject.'],
    'Rim Light': ['Rim light', 'A thin line of light draws the outline.'],
    Volumetric: ['Light rays', 'Visible beams in the haze.'],
    'Low Key': ['Dark', 'Dark background and little light.'],
    'High Key': ['Bright', 'Everything very bright, almost no shadow.']
  },
  angle: {
    'Top-down': ['Straight from above', 'Camera at 90 degrees over the subject.'],
    Frontal: ['Front', 'Camera straight in front.'],
    '3/4': ['Three-quarter', 'Half turned. Shows front and side.'],
    'Low Angle': ['Low angle', 'Low camera. The subject looks imposing.'],
    'Eye Level': ['Eye level', 'Camera at the height of the subject.'],
    Overhead: ['High angle', 'High camera, looking down diagonally.'],
    "Worm's Eye": ["Worm's eye", 'Camera on the floor, looking up.']
  },
  distance: {
    closeup: ['Close-up', 'The face or detail fills the image.'],
    portrait: ['Medium shot', 'From the waist up.'],
    american: ['Medium-wide', 'From the knees up.'],
    full: ['Full body', 'The whole subject is visible.'],
    wide: ['Wide shot', 'The place dominates. The subject is small.']
  },
  lens: {
    '14mm': ['14mm', 'Ultra-wide. Shows a lot and stretches the edges.'],
    '24mm': ['24mm', 'Wide. Good for places.'],
    '35mm': ['35mm', 'Documentary look, surroundings visible.'],
    '50mm': ['50mm', 'Close to human vision.'],
    '85mm': ['85mm', 'Portrait lens. Soft background.'],
    '105mm macro': ['105mm macro', 'Details from very close.'],
    '135mm': ['135mm', 'Telephoto. Brings the background closer.'],
    '200mm+': ['200mm+', 'Long telephoto. The background becomes a wall of color.']
  },
  aperture: {
    'f/1.4': ['f/1.4', 'Background completely blurred.'],
    'f/2.8': ['f/2.8', 'Blurred background, still recognizable.'],
    'f/5.6': ['f/5.6', 'Background slightly soft.'],
    'f/11': ['f/11', 'Everything in focus, front to back.']
  },
  mood: {
    Alegre: ['Cheerful', 'Vivid colors and a good-day feeling.'],
    'Dramático': ['Dramatic', 'Tension, contrast and a heavy sky.'],
    Sombrio: ['Gloomy', 'Dark, cold and colorless.'],
    Calmo: ['Calm', 'Soft tones and silence.'],
    Futurista: ['Futuristic', 'Clean shapes and technology lights.'],
    'Nostálgico': ['Nostalgic', 'Looks like an old photo.']
  }
}

const ES: Table = {
  subject: {
    livre: ['Libre', ''],
    pessoa: ['Persona', ''],
    objeto_produto: ['Producto', ''],
    food: ['Comida', ''],
    moda: ['Moda', ''],
    animal: ['Animal', ''],
    ambiente_arquitetura: ['Ambiente', ''],
    veiculo: ['Vehículo', ''],
    abstrato: ['Abstracto', ''],
    paisagem: ['Paisaje', '']
  },
  style: {
    Fotorrealista: ['Fotorrealista', 'Parece una foto real.'],
    'Cinematográfico': ['Cinematográfico', 'Color y contraste de una escena de cine.'],
    'Ilustração Digital': ['Ilustración digital', 'Dibujo limpio, con formas y colores controlados.'],
    '3D Render': ['3D', 'Personajes y objetos con aspecto de animación 3D.'],
    Minimalista: ['Minimalista', 'Pocos elementos y mucho espacio vacío.'],
    Luxo: ['Lujo', 'Materiales nobles y luz controlada.'],
    Anime: ['Anime', 'Trazo de animación japonesa.'],
    Aquarela: ['Acuarela', 'Pintura transparente sobre papel.'],
    'Flat/Vetor': ['Vector', 'Formas planas y contornos limpios.'],
    'Pixel Art': ['Pixel art', 'Bloques de píxeles, como juegos antiguos.'],
    'Pintura a Óleo': ['Pintura al óleo', 'Pinceladas gruesas y textura de lienzo.'],
    Cyberpunk: ['Cyberpunk', 'Neón, lluvia y tecnología futurista.'],
    'Arte Fantasia': ['Fantasía', 'Mundo mágico, lleno de detalles.'],
    'Retrô/Vintage': ['Retro', 'Colores y textura de décadas pasadas.'],
    'Pop Art': ['Pop art', 'Colores fuertes y puntos de impresión.'],
    Surreal: ['Surrealista', 'Combinaciones imposibles, como en un sueño.'],
    Editorial: ['Editorial', 'Dirección de arte de revista.'],
    'Concept Art': ['Concept art', 'Pintura suelta, de juegos y películas.']
  },
  lighting: {
    'Golden Hour': ['Hora dorada', 'Luz baja, cálida y dorada.'],
    Neon: ['Neón', 'Luces de colores de letreros, de noche.'],
    'Studio Softbox': ['Estudio', 'Luz suave y uniforme de estudio.'],
    Natural: ['Natural', 'Luz del día, sin efectos.'],
    Dramatic: ['Dramática', 'Luz fuerte de un lado, sombra del otro.'],
    Backlit: ['Contraluz', 'La luz viene de detrás del sujeto.'],
    'Rim Light': ['Luz de contorno', 'Un hilo de luz dibuja la silueta.'],
    Volumetric: ['Rayos de luz', 'Haces visibles en la niebla.'],
    'Low Key': ['Oscura', 'Fondo oscuro y poca luz.'],
    'High Key': ['Clara', 'Todo muy claro, casi sin sombras.']
  },
  angle: {
    'Top-down': ['Desde arriba, recto', 'Cámara a 90 grados sobre el sujeto.'],
    Frontal: ['De frente', 'Cámara recta, justo de frente.'],
    '3/4': ['Tres cuartos', 'Medio de lado. Muestra frente y lateral.'],
    'Low Angle': ['Contrapicado', 'Cámara baja. El sujeto parece imponente.'],
    'Eye Level': ['Altura de los ojos', 'Cámara a la altura del sujeto.'],
    Overhead: ['Picado', 'Cámara alta, mirando en diagonal.'],
    "Worm's Eye": ['Desde el suelo', 'Cámara en el suelo, mirando hacia arriba.']
  },
  distance: {
    closeup: ['Primer plano', 'El rostro o el detalle llena la imagen.'],
    portrait: ['Plano medio', 'De la cintura hacia arriba.'],
    american: ['Plano americano', 'De las rodillas hacia arriba.'],
    full: ['Cuerpo entero', 'Se ve todo el sujeto.'],
    wide: ['Plano general', 'Domina el lugar. El sujeto queda pequeño.']
  },
  lens: {
    '14mm': ['14mm', 'Ultra gran angular. Muestra mucho y estira los bordes.'],
    '24mm': ['24mm', 'Gran angular. Bueno para lugares.'],
    '35mm': ['35mm', 'Mirada de reportaje, con el entorno visible.'],
    '50mm': ['50mm', 'Cerca de la visión humana.'],
    '85mm': ['85mm', 'Lente de retrato. Fondo suave.'],
    '105mm macro': ['105mm macro', 'Detalles muy de cerca.'],
    '135mm': ['135mm', 'Teleobjetivo. Acerca el fondo.'],
    '200mm+': ['200mm+', 'Tele largo. El fondo se vuelve una pared de color.']
  },
  aperture: {
    'f/1.4': ['f/1.4', 'Fondo totalmente desenfocado.'],
    'f/2.8': ['f/2.8', 'Fondo desenfocado, aún reconocible.'],
    'f/5.6': ['f/5.6', 'Fondo ligeramente suave.'],
    'f/11': ['f/11', 'Todo enfocado, de adelante atrás.']
  },
  mood: {
    Alegre: ['Alegre', 'Colores vivos y sensación de buen día.'],
    'Dramático': ['Dramático', 'Tensión, contraste y cielo cargado.'],
    Sombrio: ['Sombrío', 'Oscuro, frío y sin color.'],
    Calmo: ['Tranquilo', 'Tonos suaves y silencio.'],
    Futurista: ['Futurista', 'Formas limpias y luces de tecnología.'],
    'Nostálgico': ['Nostálgico', 'Parece una foto antigua.']
  }
}

const ZH: Table = {
  subject: {
    livre: ['自由', ''],
    pessoa: ['人物', ''],
    objeto_produto: ['产品', ''],
    food: ['美食', ''],
    moda: ['时尚', ''],
    animal: ['动物', ''],
    ambiente_arquitetura: ['室内', ''],
    veiculo: ['车辆', ''],
    abstrato: ['抽象', ''],
    paisagem: ['风景', '']
  },
  style: {
    Fotorrealista: ['写实', '看起来像真实照片。'],
    'Cinematográfico': ['电影感', '电影画面的色彩和对比。'],
    'Ilustração Digital': ['数字插画', '干净的绘画，形状和颜色可控。'],
    '3D Render': ['3D', '三维动画质感的角色和物体。'],
    Minimalista: ['极简', '元素很少，留白很多。'],
    Luxo: ['奢华', '高级材质和精确布光。'],
    Anime: ['动漫', '日本动画线条。'],
    Aquarela: ['水彩', '纸上的透明颜料。'],
    'Flat/Vetor': ['矢量', '平面形状和干净轮廓。'],
    'Pixel Art': ['像素画', '像素方块，像老游戏。'],
    'Pintura a Óleo': ['油画', '厚重笔触和画布纹理。'],
    Cyberpunk: ['赛博朋克', '霓虹、雨和未来科技。'],
    'Arte Fantasia': ['奇幻', '细节丰富的魔法世界。'],
    'Retrô/Vintage': ['复古', '过去年代的色彩和质感。'],
    'Pop Art': ['波普', '强烈色彩和印刷网点。'],
    Surreal: ['超现实', '梦境般不可能的组合。'],
    Editorial: ['杂志风', '杂志的艺术指导。'],
    'Concept Art': ['概念设计', '游戏和电影的写意绘画。']
  },
  lighting: {
    'Golden Hour': ['黄金时刻', '低角度的温暖金色光。'],
    Neon: ['霓虹', '夜晚彩色招牌灯光。'],
    'Studio Softbox': ['影棚', '柔和均匀的影棚光。'],
    Natural: ['自然光', '日光，没有效果。'],
    Dramatic: ['戏剧光', '一侧强光，另一侧阴影。'],
    Backlit: ['逆光', '光从主体后方照来。'],
    'Rim Light': ['轮廓光', '一道细光勾出轮廓。'],
    Volumetric: ['光束', '雾气中可见的光线。'],
    'Low Key': ['暗调', '暗背景，光线很少。'],
    'High Key': ['亮调', '整体明亮，几乎无阴影。']
  },
  angle: {
    'Top-down': ['正上方', '相机在主体正上方 90 度。'],
    Frontal: ['正面', '相机正对主体。'],
    '3/4': ['四分之三', '半侧面，同时看到正面和侧面。'],
    'Low Angle': ['低角度', '相机较低，主体显得高大。'],
    'Eye Level': ['平视', '相机与主体同高。'],
    Overhead: ['俯视', '相机在高处斜向下看。'],
    "Worm's Eye": ['仰视', '相机贴地向上看。']
  },
  distance: {
    closeup: ['特写', '面部或细节占满画面。'],
    portrait: ['中景', '腰部以上。'],
    american: ['中远景', '膝盖以上。'],
    full: ['全身', '主体完整可见。'],
    wide: ['远景', '环境为主，主体很小。']
  },
  lens: {
    '14mm': ['14mm', '超广角，视野大，边缘拉伸。'],
    '24mm': ['24mm', '广角，适合环境。'],
    '35mm': ['35mm', '纪实感，看得到周围。'],
    '50mm': ['50mm', '接近人眼视角。'],
    '85mm': ['85mm', '人像镜头，背景柔和。'],
    '105mm macro': ['105mm 微距', '非常近的细节。'],
    '135mm': ['135mm', '长焦，把背景拉近。'],
    '200mm+': ['200mm+', '超长焦，背景变成一片颜色。']
  },
  aperture: {
    'f/1.4': ['f/1.4', '背景完全虚化。'],
    'f/2.8': ['f/2.8', '背景虚化，仍可辨认。'],
    'f/5.6': ['f/5.6', '背景略微柔和。'],
    'f/11': ['f/11', '从前到后全部清晰。']
  },
  mood: {
    Alegre: ['欢快', '鲜艳的颜色，好天气的感觉。'],
    'Dramático': ['戏剧性', '紧张、对比强、天空沉重。'],
    Sombrio: ['阴郁', '黑暗、寒冷、没有颜色。'],
    Calmo: ['平静', '柔和的色调和宁静。'],
    Futurista: ['未来感', '干净的形状和科技灯光。'],
    'Nostálgico': ['怀旧', '像一张老照片。']
  }
}

const TABLES = { pt: PT, en: EN, es: ES, zh: ZH }

/** The readable name and explanation of an option; an unknown value keeps its own text. */
export function directionText(group: DirectionGroup, value: string): { label: string; hint: string } {
  const entry = TABLES[activeLangOf()][group]?.[value]
  return entry ? { label: entry[0], hint: entry[1] } : { label: value, hint: '' }
}
