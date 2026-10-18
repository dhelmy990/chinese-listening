#include <jni.h>

#include <memory>
#include <mutex>
#include <stdexcept>
#include <string>
#include <vector>

#include <ctranslate2/models/whisper.h>
#include <ctranslate2/translator.h>
#include <sentencepiece_processor.h>

#include "native_input.h"

namespace {
std::mutex whisper_mutex;
std::mutex translator_mutex;
std::unique_ptr<ctranslate2::models::Whisper> whisper;
std::unique_ptr<ctranslate2::Translator> translator;
std::unique_ptr<sentencepiece::SentencePieceProcessor> source_tokenizer;
std::unique_ptr<sentencepiece::SentencePieceProcessor> target_tokenizer;
std::string whisper_path;
std::string translator_path;

void fail(JNIEnv* env, const char* message) {
    if (!env->ExceptionCheck()) {
        jclass type = env->FindClass("java/lang/IllegalStateException");
        if (type) env->ThrowNew(type, message);
    }
}

std::string read_string(JNIEnv* env, jstring value) {
    if (!value) throw std::invalid_argument("String must not be null");
    const jsize length = env->GetStringLength(value);
    const jchar* chars = env->GetStringChars(value, nullptr);
    if (!chars) throw std::runtime_error("Unable to read Java string");
    std::u16string text;
    try {
        text.assign(reinterpret_cast<const char16_t*>(chars), static_cast<size_t>(length));
    } catch (...) {
        env->ReleaseStringChars(value, chars);
        throw;
    }
    env->ReleaseStringChars(value, chars);
    return ning::to_utf8(text);
}

jstring write_string(JNIEnv* env, const std::string& value) {
    const auto text = ning::from_utf8(value);
    return env->NewString(reinterpret_cast<const jchar*>(text.data()), static_cast<jsize>(text.size()));
}

void check_sentencepiece(const sentencepiece::util::Status& status) {
    if (!status.ok()) throw std::runtime_error(status.ToString());
}

// Caller holds translator_mutex for model and tokenizer lifetime safety.
std::vector<std::string> translate_tokens(const std::vector<std::string>& tokens) {
    if (!translator) throw std::runtime_error("Translator has not been loaded");
    if (tokens.empty() || tokens.size() > 512)
        throw std::invalid_argument("Translation requires 1 to 512 source tokens");
    ctranslate2::TranslationOptions options;
    options.beam_size = 4;
    options.max_decoding_length = 512;
    const auto result = translator->translate_batch({tokens}, options);
    return result.at(0).hypotheses.at(0);
}

ctranslate2::ReplicaPoolConfig pool_config(int threads) {
    if (threads < 1 || threads > 32)
        throw std::invalid_argument("Thread count must be between 1 and 32");
    ctranslate2::ReplicaPoolConfig config;
    config.num_threads_per_replica = threads;
    return config;
}

std::string model_path(JNIEnv* env, jstring directory) {
    auto path = read_string(env, directory);
    if (path.empty() || path.find('\0') != std::string::npos)
        throw std::invalid_argument("Model directory is empty or contains a null character");
    return path;
}
} // namespace

extern "C" JNIEXPORT void JNICALL
Java_com_ning_chinese_NativeEngine_loadWhisper(JNIEnv* env, jclass, jstring directory, jint threads) {
    try {
        const auto path = model_path(env, directory);
        const auto config = pool_config(threads);
        std::lock_guard<std::mutex> lock(whisper_mutex);
        if (whisper) {
            if (whisper_path != path) throw std::runtime_error("Whisper is already loaded from another directory");
            return;
        }
        auto model = std::make_unique<ctranslate2::models::Whisper>(
            path, ctranslate2::Device::CPU, ctranslate2::ComputeType::INT8,
            std::vector<int>{0}, false, config);
        if (model->n_mels() != 128 || !model->is_multilingual())
            throw std::runtime_error("A multilingual 128-mel Turbo model is required");
        whisper_path = path;
        whisper = std::move(model);
    } catch (const std::exception& error) { fail(env, error.what()); }
    catch (...) { fail(env, "Unknown Whisper loading error"); }
}

extern "C" JNIEXPORT jintArray JNICALL
Java_com_ning_chinese_NativeEngine_transcribe(JNIEnv* env, jclass, jfloatArray mel,
                                            jint frames, jintArray prompt_array) {
    try {
        if (!mel || !prompt_array) throw std::invalid_argument("Mel and prompt must not be null");
        const jsize mel_length = env->GetArrayLength(mel);
        ning::validate_mel_shape(static_cast<size_t>(mel_length), frames);
        const jsize prompt_length = env->GetArrayLength(prompt_array);
        if (prompt_length < 1 || prompt_length >= 448)
            throw std::invalid_argument("Whisper prompt must contain 1 to 447 tokens");
        std::vector<float> features(static_cast<size_t>(mel_length));
        std::vector<jint> java_prompt(static_cast<size_t>(prompt_length));
        env->GetFloatArrayRegion(mel, 0, mel_length, features.data());
        env->GetIntArrayRegion(prompt_array, 0, prompt_length, java_prompt.data());
        if (env->ExceptionCheck()) return nullptr;
        ning::validate_finite(features);
        std::vector<int> prompt(java_prompt.begin(), java_prompt.end());
        ning::validate_prompt(prompt);

        std::lock_guard<std::mutex> lock(whisper_mutex);
        if (!whisper) throw std::runtime_error("Whisper has not been loaded");
        ctranslate2::StorageView input({1, 128, frames}, features);
        ctranslate2::models::WhisperOptions options;
        options.beam_size = 1;
        options.max_length = 448;
        // Turbo's multilingual control tokens, matching faster-whisper suppression.
        options.suppress_tokens = {-1, 50258, 50359, 50360, 50361, 50362, 50363};
        std::vector<size_t> token_ids(prompt.begin(), prompt.end());
        auto results = whisper->generate(input, std::vector<std::vector<size_t>>{token_ids}, options);
        const auto result = results.at(0).get();
        const auto& sequence = result.sequences_ids.at(0);
        std::vector<jint> output(sequence.begin(), sequence.end());
        jintArray array = env->NewIntArray(static_cast<jsize>(output.size()));
        if (array) env->SetIntArrayRegion(array, 0, static_cast<jsize>(output.size()), output.data());
        return array;
    } catch (const std::exception& error) { fail(env, error.what()); }
    catch (...) { fail(env, "Unknown Whisper inference error"); }
    return nullptr;
}

extern "C" JNIEXPORT void JNICALL
Java_com_ning_chinese_NativeEngine_loadTranslator(JNIEnv* env, jclass, jstring directory, jint threads) {
    try {
        const auto path = model_path(env, directory);
        const auto config = pool_config(threads);
        std::lock_guard<std::mutex> lock(translator_mutex);
        if (translator) {
            if (translator_path != path) throw std::runtime_error("Translator is already loaded from another directory");
            return;
        }
        auto source = std::make_unique<sentencepiece::SentencePieceProcessor>();
        auto target = std::make_unique<sentencepiece::SentencePieceProcessor>();
        check_sentencepiece(source->Load(path + "/source.spm"));
        check_sentencepiece(target->Load(path + "/target.spm"));
        auto model = std::make_unique<ctranslate2::Translator>(
            path, ctranslate2::Device::CPU, ctranslate2::ComputeType::FLOAT32,
            std::vector<int>{0}, false, config);
        translator_path = path;
        source_tokenizer = std::move(source);
        target_tokenizer = std::move(target);
        translator = std::move(model);
    } catch (const std::exception& error) { fail(env, error.what()); }
    catch (...) { fail(env, "Unknown translator loading error"); }
}

extern "C" JNIEXPORT jobjectArray JNICALL
Java_com_ning_chinese_NativeEngine_translate(JNIEnv* env, jclass, jobjectArray source) {
    try {
        if (!source) throw std::invalid_argument("Source tokens must not be null");
        const jsize count = env->GetArrayLength(source);
        if (count < 1 || count > 512)
            throw std::invalid_argument("Translation requires 1 to 512 source tokens");
        std::vector<std::string> tokens;
        tokens.reserve(static_cast<size_t>(count));
        for (jsize i = 0; i < count; ++i) {
            auto token = static_cast<jstring>(env->GetObjectArrayElement(source, i));
            try { tokens.push_back(read_string(env, token)); }
            catch (...) { if (token) env->DeleteLocalRef(token); throw; }
            env->DeleteLocalRef(token);
            if (tokens.back().empty()) throw std::invalid_argument("Source tokens must not be empty");
        }
        std::lock_guard<std::mutex> lock(translator_mutex);
        const auto output = translate_tokens(tokens);
        jclass string_class = env->FindClass("java/lang/String");
        if (!string_class) return nullptr;
        jobjectArray array = env->NewObjectArray(static_cast<jsize>(output.size()), string_class, nullptr);
        env->DeleteLocalRef(string_class);
        if (!array) return nullptr;
        for (size_t i = 0; i < output.size(); ++i) {
            jstring token = write_string(env, output[i]);
            if (!token) return nullptr;
            env->SetObjectArrayElement(array, static_cast<jsize>(i), token);
            env->DeleteLocalRef(token);
            if (env->ExceptionCheck()) return nullptr;
        }
        return array;
    } catch (const std::exception& error) { fail(env, error.what()); }
    catch (...) { fail(env, "Unknown translation inference error"); }
    return nullptr;
}

extern "C" JNIEXPORT jstring JNICALL
Java_com_ning_chinese_NativeEngine_translateText(JNIEnv* env, jclass, jstring text) {
    try {
        const auto input = read_string(env, text);
        if (input.empty()) throw std::invalid_argument("Translation text must not be empty");
        std::lock_guard<std::mutex> lock(translator_mutex);
        if (!translator) throw std::runtime_error("Translator has not been loaded");
        std::vector<std::string> tokens;
        check_sentencepiece(source_tokenizer->Encode(input, &tokens));
        tokens.emplace_back("</s>");
        const auto translated = translate_tokens(tokens);
        std::string output;
        check_sentencepiece(target_tokenizer->Decode(translated, &output));
        return write_string(env, output);
    } catch (const std::exception& error) { fail(env, error.what()); }
    catch (...) { fail(env, "Unknown text translation error"); }
    return nullptr;
}
